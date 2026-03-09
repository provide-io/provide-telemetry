#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Final

BAD_STAT_KEYS: Final[tuple[str, ...]] = (
    "segfault",
    "suspicious",
    "no_tests",
    "check_was_interrupted_by_user",
)

CONFIG_FILES: Final[tuple[str, ...]] = (
    "pyproject.toml",
    ".pytest.ini",
    "pytest.ini",
)


def _uv_mutmut_cmd(python_version: str | None, *args: str) -> list[str]:
    base = ["uv", "run"]
    if python_version:
        base.extend(["--python", python_version])
    return [*base, "mutmut", *args]


def _mutmut_env() -> dict[str, str]:
    env = dict(os.environ)
    shims_dir = (Path(__file__).resolve().parent / "_mutmut_shims").as_posix()
    current_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{shims_dir}:{current_path}" if current_path else shims_dir
    return env


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(cmd))
    completed = subprocess.run(cmd, check=False, env=env)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(cmd)}")


def _seed_mutants_config() -> None:
    mutants = Path("mutants")
    mutants.mkdir(parents=True, exist_ok=True)
    for config_name in CONFIG_FILES:
        src = Path(config_name)
        if src.exists():
            dst = mutants / config_name
            shutil.copy2(src, dst)


def _half_cpu_count() -> int:
    count = os.cpu_count() or 1
    return max(1, count // 2)


def _read_stats(path: Path) -> dict[str, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {k: int(v) for k, v in payload.items()}


def _is_clean(stats: dict[str, int]) -> bool:
    if int(stats.get("total", 0)) <= 0:
        return False
    return all(int(stats.get(key, 0)) == 0 for key in BAD_STAT_KEYS)


def _mutation_score(stats: dict[str, int]) -> float:
    total = int(stats.get("total", 0))
    if total <= 0:
        return 0.0
    killed = int(stats.get("killed", 0))
    return (killed / total) * 100.0


def run_mutation_gate(
    python_version: str | None,
    max_children: int,
    retries: int,
    min_mutation_score: float,
) -> dict[str, int]:
    attempts = retries + 1
    stats_path = Path("mutants/mutmut-cicd-stats.json")
    last_stats: dict[str, int] = {}
    mutation_env = _mutmut_env()

    for attempt in range(1, attempts + 1):
        mutants_dir = Path("mutants")
        if mutants_dir.exists():
            shutil.rmtree(mutants_dir)
        _seed_mutants_config()

        children = max_children if attempt == 1 else 1
        print(f"Running mutation attempt {attempt}/{attempts} with max-children={children}")

        _run(_uv_mutmut_cmd(python_version, "run", "--max-children", str(children)), env=mutation_env)
        _run(_uv_mutmut_cmd(python_version, "export-cicd-stats"), env=mutation_env)
        last_stats = _read_stats(stats_path)
        score = _mutation_score(last_stats)
        print(f"mutation_score={score:.2f}")
        print(json.dumps(last_stats, indent=2, sort_keys=True))

        if _is_clean(last_stats) and score >= min_mutation_score:
            return last_stats
        if attempt < attempts:
            print("Mutation gate not clean; retrying in single-worker mode.")

    score = _mutation_score(last_stats)
    raise RuntimeError(
        "mutation gate failed: "
        f"score={score:.2f} min_required={min_mutation_score:.2f} "
        f"stats={json.dumps(last_stats, sort_keys=True)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run strict mutmut gate with retries.")
    parser.add_argument("--python-version", default="3.11", help="Python version passed to `uv run --python`.")
    parser.add_argument(
        "--max-children",
        type=int,
        default=None,
        help="Initial mutmut worker count (defaults to half CPU count).",
    )
    parser.add_argument("--retries", type=int, default=1, help="Number of retries after initial failure.")
    parser.add_argument(
        "--min-mutation-score",
        type=float,
        default=80.0,
        help="Minimum mutation score required to pass (killed/total * 100).",
    )
    args = parser.parse_args()
    half_cpus = _half_cpu_count()
    requested_children = args.max_children if args.max_children is not None else half_cpus
    max_children = min(max(1, requested_children), half_cpus)

    try:
        run_mutation_gate(args.python_version, max_children, args.retries, args.min_mutation_score)
    except RuntimeError as exc:
        print(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
