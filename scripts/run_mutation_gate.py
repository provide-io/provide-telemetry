#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess  # nosec
from pathlib import Path
from typing import Final

# Any non-zero count here fails the gate. "survived" is in the list because the
# documented contract is a 100% kill score, not a high one: without it a run
# with live survivors passed as long as the score cleared the floor below, which
# is how two killable mutants sat in the tree while the gate reported clean.
BAD_STAT_KEYS: Final[tuple[str, ...]] = (
    "segfault",
    "suspicious",
    "survived",
    "no_tests",
    "timeout",
    "check_was_interrupted_by_user",
)
# An additional floor, not the bar — _is_clean() above is the bar. Kept below
# 100 so a run that somehow reports no survivors but a short total still fails
# on the score rather than passing silently.
DEFAULT_MIN_MUTATION_SCORE: Final[float] = 95.0

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


# mutmut raises this when its per-mutant pytest invocation exits 4 (usage
# error). The raise happens inside the forked child, before ``os._exit(result)``,
# so the child dies on an uncaught exception with a nonzero status — and a
# nonzero child status is exactly how mutmut records "the tests detected this
# mutant". Every such mutant is therefore counted as killed without a test ever
# having run against it, and the run still reports 100% and exits 0.
#
# The one occurrence found so far (110 mutants of 4767) was a node id that is
# not stable across two collections in the same interpreter: pytest re-escapes a
# parametrize id it has already escaped, so the ids mutmut recorded during its
# first (stats) collection stopped matching on every later pytest.main() call,
# and pytest exited 4 with "not found". That is fixed at the source — see
# tests/tooling/test_parametrize_id_stability.py, which fails the suite if such
# an id reappears. This counter stays as the backstop: it cannot repair a run,
# but it refuses to certify one whose kills were never earned.
_EXEC_FAILURE_MARKER = "BadTestExecutionCommandsException"


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> str:
    """Run *cmd*, streaming its output, and return what it printed."""
    print("+", " ".join(cmd))
    completed = subprocess.run(cmd, check=False, env=env, capture_output=True, text=True)  # nosec
    output = (completed.stdout or "") + (completed.stderr or "")
    print(output, end="")
    if completed.returncode != 0:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(cmd)}")
    return output


def count_exec_failures(output: str) -> int:
    """Count mutants whose test command failed to run.

    The marker appears twice per occurrence — once in the traceback frame and
    once in the raised message — so the raw match count is halved.
    """
    return output.count(_EXEC_FAILURE_MARKER) // 2


def _seed_mutants_config() -> None:
    mutants = Path("mutants")
    mutants.mkdir(parents=True, exist_ok=True)
    for config_name in CONFIG_FILES:
        src = Path(config_name)
        if src.exists():
            dst = mutants / config_name
            shutil.copy2(src, dst)


def _third_cpu_count() -> int:
    count = os.cpu_count() or 1
    return max(1, count // 3)


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

        run_output = _run(_uv_mutmut_cmd(python_version, "run", "--max-children", str(children)), env=mutation_env)
        _run(_uv_mutmut_cmd(python_version, "export-cicd-stats"), env=mutation_env)
        last_stats = _read_stats(stats_path)
        score = _mutation_score(last_stats)
        exec_failures = count_exec_failures(run_output)
        print(f"mutation_score={score:.2f}")
        print(json.dumps(last_stats, indent=2, sort_keys=True))
        if exec_failures:
            print(f"exec_failures={exec_failures} (mutants counted as killed without a test running)")

        if _is_clean(last_stats) and score >= min_mutation_score and exec_failures == 0:
            return last_stats
        if exec_failures and attempt == attempts:
            raise RuntimeError(
                f"mutation gate failed: {exec_failures} mutant(s) had their pytest invocation "
                "fail to execute. mutmut counts a child that dies on an uncaught "
                "BadTestExecutionCommandsException as killed, because it exits nonzero — so "
                f"those {exec_failures} results are unearned and the reported score "
                f"({score:.2f}) is that much too high."
            )
        if attempt < attempts:
            print("Mutation gate not clean; retrying in single-worker mode.")

    # Log surviving mutants for debugging CI failures.
    try:
        result = subprocess.run(
            _uv_mutmut_cmd(python_version, "results"),
            capture_output=True,
            text=True,
            env=mutation_env,
        )
        survivors = [line.strip() for line in result.stdout.splitlines() if "survived" in line]
        if survivors:
            print("Surviving mutants:")
            for s in survivors:
                print(f"  {s}")
    except Exception:
        pass

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
        help="Initial mutmut worker count (defaults to 1/3 CPU count).",
    )
    parser.add_argument("--retries", type=int, default=1, help="Number of retries after initial failure.")
    parser.add_argument(
        "--min-mutation-score",
        type=float,
        default=DEFAULT_MIN_MUTATION_SCORE,
        help="Minimum mutation score required to pass (killed/total * 100).",
    )
    args = parser.parse_args()
    max_cpus = _third_cpu_count()
    requested_children = args.max_children if args.max_children is not None else max_cpus
    max_children = min(max(1, requested_children), max_cpus)

    try:
        run_mutation_gate(args.python_version, max_children, args.retries, args.min_mutation_score)
    except RuntimeError as exc:
        print(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
