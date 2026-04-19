#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Run behavioral parity tests across all four language implementations.

Each language has its own parity test suite that validates the same
spec/behavioral_fixtures.yaml contracts. This script runs all four suites
and reports a unified pass/fail matrix.

By default both output-format probes (--check-output) and contract DSL probes
(--check-contracts) are enabled.  Use --skip-output or --skip-contracts to
disable them for ad-hoc debugging.

Usage:
    python spec/run_behavioral_parity.py                          # run all languages (strict)
    python spec/run_behavioral_parity.py --lang python,go         # run subset
    python spec/run_behavioral_parity.py --skip-output            # skip log-output probes
    python spec/run_behavioral_parity.py --skip-contracts         # skip contract DSL probes

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
    """How to run parity tests for one language.

    ``run_cmds`` is the authoritative list of commands to execute in sequence.
    Every command in the list must succeed for the runner to be considered
    passing.  Use multiple entries when the language's test suite is split
    across several binaries or invocations (e.g. Rust integration test crates).
    """

    name: str
    label: str
    check_cmd: list[str]  # command to verify runtime is available
    run_cmds: list[list[str]]  # one or more commands to run the full parity suite
    cwd: Path  # working directory
    env_extra: dict[str, str] = field(default_factory=dict)


def _runners(repo: Path) -> list[LanguageRunner]:
    return [
        LanguageRunner(
            name="python",
            label="Python",
            check_cmd=["uv", "--version"],
            # tests/parity/ directory run covers all Python parity test files.
            run_cmds=[
                [
                    "uv",
                    "run",
                    "python",
                    "scripts/run_pytest_gate.py",
                    "tests/parity/",
                    "--no-cov",
                    "-q",
                ],
            ],
            cwd=repo,
        ),
        LanguageRunner(
            name="typescript",
            label="TypeScript",
            check_cmd=["node", "--version"],
            # Run all parity files counted by check_fixture_coverage.py:
            #   tests/parity.test.ts          — core parity suite
            #   tests/parity.fixtures.test.ts — extra fixture-category cases
            #                                   (split out of parity.test.ts to
            #                                    keep both files under 500 LOC)
            #   tests/endpoint.test.ts        — endpoint-validation parity
            # The whole test directory is NOT used to avoid attributing unrelated
            # failures to the parity gate.
            run_cmds=[
                [
                    "npx",
                    "vitest",
                    "run",
                    "tests/parity.test.ts",
                    "tests/parity.fixtures.test.ts",
                    "tests/endpoint.test.ts",
                ],
            ],
            cwd=repo / "typescript",
        ),
        LanguageRunner(
            name="go",
            label="Go",
            check_cmd=["go", "version"],
            # -run accepts a regex: TestParity matches TestParity_* files; the pipe
            # also matches TestEndpointValidationParity from parity_endpoint_test.go
            # which does not carry the TestParity prefix.
            run_cmds=[
                [
                    "go",
                    "test",
                    "-run",
                    "TestParity|TestEndpointValidationParity",
                    "-v",
                    "-count=1",
                    "./...",
                ],
            ],
            cwd=repo / "go",
        ),
        LanguageRunner(
            name="rust",
            label="Rust",
            check_cmd=[_CARGO_BIN, "--version"],
            # Each integration test file is a separate binary in Rust; --test only
            # selects one binary at a time.  We invoke cargo test once per parity
            # binary so that all three files counted by check_fixture_coverage.py
            # are actually executed:
            #   parity_test         (rust/tests/parity_test.rs)
            #   parity_extra_test   (rust/tests/parity_extra_test.rs)
            #   parity_pii_fixes_test (rust/tests/parity_pii_fixes_test.rs)
            # --test-threads=1 is required for all three because they share global
            # state (logging config, PII rules, queue policy).
            # RUST_MIN_STACK=8388608 is set in env_extra for all invocations.
            run_cmds=[
                [_CARGO_BIN, "--locked", "test", "--test", "parity_test", "--", "--test-threads=1"],
                [_CARGO_BIN, "--locked", "test", "--test", "parity_extra_test", "--", "--test-threads=1"],
                [
                    _CARGO_BIN,
                    "--locked",
                    "test",
                    "--test",
                    "parity_pii_fixes_test",
                    "--",
                    "--test-threads=1",
                ],
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
    """Run all parity commands for a language and return an aggregated Result.

    Each command in ``runner.run_cmds`` is executed in order.  The first
    failure stops execution and returns a "fail" result so that later commands
    (which may depend on compilation artefacts from earlier ones) are not run
    against a broken build.
    """
    env = {**os.environ, **runner.env_extra}
    start = time.monotonic()
    all_output: list[str] = []
    for cmd in runner.run_cmds:
        try:
            proc = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                cwd=runner.cwd,
                env=env,
                timeout=timeout,
            )
            all_output.append((proc.stdout + proc.stderr).strip())
            if proc.returncode != 0:
                elapsed = time.monotonic() - start
                return Result(
                    lang=runner.name,
                    label=runner.label,
                    status="fail",
                    duration_s=elapsed,
                    output="\n".join(all_output),
                )
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - start
            all_output.append(f"TIMEOUT after {timeout}s")
            return Result(
                lang=runner.name,
                label=runner.label,
                status="fail",
                duration_s=elapsed,
                output="\n".join(all_output),
            )
    elapsed = time.monotonic() - start
    return Result(
        lang=runner.name,
        label=runner.label,
        status="pass",
        duration_s=elapsed,
        output="\n".join(all_output),
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
        "--skip-output",
        action="store_true",
        default=False,
        help="Skip log-output probes (default: probes are run)",
    )
    parser.add_argument(
        "--skip-contracts",
        action="store_true",
        default=False,
        help="Skip contract probe DSL cases (default: cases are run)",
    )
    # Legacy opt-in flags kept for backward compatibility — they are now no-ops
    # because output and contract checks are on by default.  Passing them still
    # works and produces the same result.
    parser.add_argument("--check-output", action="store_true", default=True, help=argparse.SUPPRESS)
    parser.add_argument("--check-contracts", action="store_true", default=True, help=argparse.SUPPRESS)
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

    if not args.skip_output:
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

    if not args.skip_contracts:
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
