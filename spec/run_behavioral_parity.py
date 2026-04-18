#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Run behavioral parity tests across all four language implementations.

Each language has its own parity test suite that validates the same
spec/behavioral_fixtures.yaml contracts. This script runs all four suites
and reports a unified pass/fail matrix.

Usage:
    python spec/run_behavioral_parity.py                    # run all languages
    python spec/run_behavioral_parity.py --lang python,go   # run subset
    python spec/run_behavioral_parity.py --check-output     # also compare JSON log output

Exit code 0 if every checked language passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

_SPEC_DIR = Path(__file__).resolve().parent
if str(_SPEC_DIR) not in sys.path:
    sys.path.insert(0, str(_SPEC_DIR))

from parity_probe_support import (  # noqa: E402
    run_contract_cases,
    run_output_check,
    run_runtime_probe_check,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_RUNTIME_PROBE_FIXTURES = _REPO_ROOT / "spec" / "runtime_probe_fixtures.yaml"


def _find_rust_toolchain() -> tuple[str, dict[str, str]]:
    """Return (cargo_bin, env_overrides) ensuring a coherent Rust toolchain.

    uv run python injects its own older cargo AND rustc into PATH for building
    Python packages.  Prepending ~/.cargo/bin to PATH ensures both cargo and
    rustc resolve from the same rustup-managed toolchain rather than the
    uv-injected one.
    """
    cargo_dir = Path.home() / ".cargo" / "bin"
    if (cargo_dir / "cargo").is_file():
        cargo_bin = str(cargo_dir / "cargo")
        env_overrides: dict[str, str] = {
            "PATH": f"{cargo_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        }
    else:
        cargo_bin = shutil.which("cargo") or "cargo"
        env_overrides = {}
    return cargo_bin, env_overrides


_CARGO_BIN: str
_CARGO_ENV: dict[str, str]
_CARGO_BIN, _CARGO_ENV = _find_rust_toolchain()

# ---------------------------------------------------------------------------
# Language runner configuration
# ---------------------------------------------------------------------------

_PASS = "\033[32mPASS\033[0m"  # noqa: S105
_FAIL = "\033[31mFAIL\033[0m"
_SKIP = "\033[33mSKIP\033[0m"


@dataclass
class LanguageRunner:
    """How to run parity tests for one language."""

    name: str
    label: str
    check_cmd: list[str]  # command to verify runtime is available
    run_cmd: list[str]  # command to run the parity tests
    cwd: Path  # working directory
    env_extra: dict[str, str] = field(default_factory=dict)


def _runners(repo: Path) -> list[LanguageRunner]:
    return [
        LanguageRunner(
            name="python",
            label="Python",
            check_cmd=["uv", "--version"],
            run_cmd=[
                "uv",
                "run",
                "python",
                "scripts/run_pytest_gate.py",
                "tests/parity/",
                "--no-cov",
                "-q",
            ],
            cwd=repo,
        ),
        LanguageRunner(
            name="typescript",
            label="TypeScript",
            check_cmd=["node", "--version"],
            run_cmd=["npx", "vitest", "run", "tests/parity.test.ts"],
            cwd=repo / "typescript",
        ),
        LanguageRunner(
            name="go",
            label="Go",
            check_cmd=["go", "version"],
            run_cmd=["go", "test", "-run", "TestParity", "-v", "-count=1", "./..."],
            cwd=repo / "go",
        ),
        LanguageRunner(
            name="rust",
            label="Rust",
            check_cmd=[_CARGO_BIN, "--version"],
            run_cmd=[
                _CARGO_BIN,
                "--locked",
                "test",
                "--test",
                "parity_test",
                "--",
                "--test-threads=1",
            ],
            cwd=repo / "rust",
            # 8 MiB stack prevents overflow when all parity tests run sequentially
            # on the same thread (default 2 MiB is insufficient for deep sanitize_payload calls)
            env_extra={"RUST_MIN_STACK": "8388608", **_CARGO_ENV},
        ),
    ]


# ---------------------------------------------------------------------------
# Runner logic
# ---------------------------------------------------------------------------


@dataclass
class Result:
    lang: str
    label: str
    status: str  # "pass" | "fail" | "skip"
    duration_s: float
    output: str


def _runtime_available(runner: LanguageRunner) -> bool:
    """Return True if the runtime for this language is installed."""
    try:
        subprocess.run(  # noqa: S603
            runner.check_cmd,
            capture_output=True,
            check=True,
            cwd=runner.cwd,
            timeout=10,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _run_parity(runner: LanguageRunner, *, timeout: int = 300) -> Result:
    """Run parity tests and return a Result."""
    env = {**os.environ, **runner.env_extra}
    start = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S603
            runner.run_cmd,
            capture_output=True,
            text=True,
            cwd=runner.cwd,
            env=env,
            timeout=timeout,
        )
        elapsed = time.monotonic() - start
        status = "pass" if proc.returncode == 0 else "fail"
        output = (proc.stdout + proc.stderr).strip()
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        status = "fail"
        output = f"TIMEOUT after {timeout}s"
    return Result(
        lang=runner.name,
        label=runner.label,
        status=status,
        duration_s=elapsed,
        output=output,
    )


# ---------------------------------------------------------------------------
# Log output parity — probe execution and field comparison
# ---------------------------------------------------------------------------

_PROBE_ENV: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lang",
        default="python,typescript,go,rust",
        help="Comma-separated list of languages to check (default: all four)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds before a single language run is considered timed out (default: 300)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print full test output for failing languages",
    )
    parser.add_argument(
        "--check-output",
        action="store_true",
        help="Also run log-output probes and compare canonical JSON fields cross-language",
    )
    parser.add_argument(
        "--check-contracts",
        action="store_true",
        help="Run contract probe DSL cases",
    )
    args = parser.parse_args(argv)

    selected = {s.strip().lower() for s in args.lang.split(",")}
    runners = [r for r in _runners(_REPO_ROOT) if r.name in selected]

    if not runners:
        print(f"No runners matched --lang={args.lang!r}", file=sys.stderr)
        return 1

    results: list[Result] = []
    for runner in runners:
        if not _runtime_available(runner):
            print(f"  [{runner.label:12s}] runtime not found — skipping")
            results.append(
                Result(
                    lang=runner.name,
                    label=runner.label,
                    status="skip",
                    duration_s=0.0,
                    output="runtime not installed",
                )
            )
            continue

        print(f"  [{runner.label:12s}] running parity tests...", flush=True)
        result = _run_parity(runner, timeout=args.timeout)
        badge = _PASS if result.status == "pass" else _FAIL
        print(f"  [{runner.label:12s}] {badge}  ({result.duration_s:.1f}s)")
        results.append(result)

    # Summary table
    print()
    print("┌─────────────────┬────────┬──────────┐")
    print("│ Language        │ Status │     Time │")
    print("├─────────────────┼────────┼──────────┤")
    for r in results:
        if r.status == "pass":
            badge = "PASS"
        elif r.status == "fail":
            badge = "FAIL"
        else:
            badge = "SKIP"
        print(f"│ {r.label:<15s} │ {badge:<6s} │ {r.duration_s:6.1f}s │")
    print("└─────────────────┴────────┴──────────┘")

    any_fail = any(r.status == "fail" for r in results)
    if any_fail:
        print()
        for r in results:
            if r.status == "fail":
                print(f"── {r.label} failure output ──────────────────────────")
                print(r.output[-4000:] if len(r.output) > 4000 else r.output)
                print()
    elif args.verbose:
        for r in results:
            print(f"── {r.label} output ──────────────────────────")
            print(r.output)
            print()

    if args.check_output:
        output_ok = run_output_check(
            _REPO_ROOT,
            selected,
            _CARGO_BIN,
            _CARGO_ENV,
            _PROBE_ENV,
            verbose=args.verbose,
            timeout=args.timeout,
        )
        if not output_ok:
            any_fail = True
        try:
            runtime_ok = run_runtime_probe_check(
                _REPO_ROOT,
                selected,
                _CARGO_BIN,
                _CARGO_ENV,
                _PROBE_ENV,
                _RUNTIME_PROBE_FIXTURES,
                timeout=args.timeout,
            )
        except RuntimeError as exc:
            print(f"[runtime-probe] ERROR: {exc}", file=sys.stderr)
            runtime_ok = False
        if not runtime_ok:
            any_fail = True

    if args.check_contracts:
        contracts_ok = run_contract_cases(
            _REPO_ROOT,
            selected,
            _CARGO_BIN,
            _CARGO_ENV,
            timeout=args.timeout,
        )
        if not contracts_ok:
            any_fail = True

    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
