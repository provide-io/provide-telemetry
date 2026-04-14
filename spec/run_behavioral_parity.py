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
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

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
            check_cmd=["cargo", "--version"],
            run_cmd=[
                "cargo",
                "test",
                "--test",
                "parity_test",
                "--",
                "--test-threads=1",
            ],
            cwd=repo / "rust",
            # 8 MiB stack prevents overflow when all parity tests run sequentially
            # on the same thread (default 2 MiB is insufficient for deep sanitize_payload calls)
            env_extra={"RUST_MIN_STACK": "8388608"},
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
    import os

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

# Env vars injected into every probe process (matches spec/behavioral_fixtures.yaml).
_PROBE_ENV: dict[str, str] = {
    "PROVIDE_LOG_FORMAT": "json",
    "PROVIDE_TELEMETRY_SERVICE_NAME": "probe",
    "PROVIDE_LOG_LEVEL": "INFO",
    "PROVIDE_LOG_INCLUDE_TIMESTAMP": "false",
}

# Canonical field renames: {raw_field: canonical_field}.
# Applied before comparison so all languages share the same key names.
_FIELD_RENAMES: dict[str, str] = {
    "msg": "message",  # Go slog / some structlog variants emit "msg"
    "message": "message",  # already canonical; listed for completeness
    "time": "timestamp",
    "target": "logger_name",
    "name": "logger_name",
    "service.name": "service",
    "service.env": "env",
    "service.version": "version",
    "trace.id": "trace_id",
    "span.id": "span_id",
}

# Fields to drop after renaming (pino metadata, structlog internals).
_NOISE_FIELDS: frozenset[str] = frozenset(
    {"pid", "hostname", "v", "event", "service.name", "service.env", "service.version", "trace.id", "span.id"}
)

# Pino numeric level → canonical uppercase string.
_PINO_LEVELS: dict[int, str] = {10: "TRACE", 20: "DEBUG", 30: "INFO", 40: "WARN", 50: "ERROR", 60: "FATAL"}

# Accept UTC (Z) or any timezone offset (±HH:MM) — both are valid ISO 8601.
# Fractional seconds are optional since languages vary in precision.
_ISO8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


@dataclass
class ProbeRunner:
    """How to invoke the emit probe for one language."""

    name: str
    label: str
    cmd: list[str]
    cwd: Path
    env_extra: dict[str, str] = field(default_factory=dict)


def _probe_runners(repo: Path) -> list[ProbeRunner]:
    probes = repo / "spec" / "probes"
    return [
        ProbeRunner(
            name="python",
            label="Python",
            cmd=["uv", "run", "python", str(probes / "emit_log_python.py")],
            cwd=repo,
        ),
        ProbeRunner(
            name="go",
            label="Go",
            cmd=["go", "run", str(probes / "emit_log_go" / "main.go")],
            cwd=repo / "go" / "logger",
        ),
        ProbeRunner(
            name="typescript",
            label="TypeScript",
            cmd=["npx", "tsx", str(probes / "emit_log_typescript.ts")],
            cwd=repo / "typescript",
            # tsx resolves node_modules from file path, not cwd; point it at the
            # typescript package's node_modules so bare imports like 'pino' resolve.
            env_extra={"NODE_PATH": str(repo / "typescript" / "node_modules")},
        ),
        ProbeRunner(
            name="rust",
            label="Rust",
            cmd=["cargo", "run", "--example", "emit_log_probe", "--quiet"],
            cwd=repo / "rust",
        ),
    ]


def _normalize_log_record(raw: dict[str, object]) -> dict[str, object]:
    """Apply canonical renames, strip noise, normalise level to uppercase string."""
    result: dict[str, object] = {}
    for k, v in raw.items():
        canonical = _FIELD_RENAMES.get(k, k)
        if k not in _NOISE_FIELDS:
            result[canonical] = v
    # Normalise pino numeric level.
    level = result.get("level")
    if isinstance(level, int):
        result["level"] = _PINO_LEVELS.get(level, str(level))
    elif isinstance(level, str):
        result["level"] = level.upper()
    return result


def _run_probe(runner: ProbeRunner, *, timeout: int = 60) -> tuple[str, str]:
    """Run probe; return (combined_output, error_message_or_empty)."""
    import os

    env = {**os.environ, **_PROBE_ENV, **runner.env_extra}
    try:
        proc = subprocess.run(  # noqa: S603
            runner.cmd,
            capture_output=True,
            text=True,
            cwd=runner.cwd,
            env=env,
            timeout=timeout,
        )
        combined = (proc.stdout + proc.stderr).strip()
        if proc.returncode != 0 and not combined:
            return "", f"exit code {proc.returncode}: {proc.stderr.strip()[:200]}"
        return combined, ""
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return "", str(exc)


def _extract_json_line(output: str) -> dict[str, object] | None:
    """Find and parse the first line in output that looks like a JSON object."""
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)  # type: ignore[return-value]
            except json.JSONDecodeError:
                continue
    return None


def _compare_outputs(records: dict[str, dict[str, object]]) -> list[str]:
    """Cross-compare required fields across all language records.

    Returns a list of mismatch messages; empty list means all good.
    """
    mismatches: list[str] = []
    required = ("message", "level")
    for field_name in required:
        values = {lang: rec.get(field_name) for lang, rec in records.items()}
        unique = set(v for v in values.values() if v is not None)
        if len(unique) > 1:
            mismatches.append(
                f"  field '{field_name}' differs: " + ", ".join(f"{lang}={v!r}" for lang, v in sorted(values.items()))
            )
    # Verify timestamp format when present.
    for lang, rec in records.items():
        ts = rec.get("timestamp")
        if ts is not None and not _ISO8601_RE.match(str(ts)):
            mismatches.append(f"  {lang}: 'timestamp' is not ISO 8601: {ts!r}")
    return mismatches


def run_output_check(
    repo: Path,
    selected: set[str],
    *,
    verbose: bool = False,
    timeout: int = 60,
) -> bool:
    """Run output probes and compare canonical JSON fields.  Returns True if all pass."""
    runners = [r for r in _probe_runners(repo) if r.name in selected]
    records: dict[str, dict[str, object]] = {}
    all_ok = True

    print()
    print("── Log output parity ───────────────────────────────")
    for runner in runners:
        output, err = _run_probe(runner, timeout=timeout)
        if err:
            print(f"  [{runner.label:12s}] PROBE ERROR: {err}")
            all_ok = False
            continue
        raw = _extract_json_line(output)
        if raw is None:
            print(f"  [{runner.label:12s}] NO JSON LINE in output")
            if verbose:
                print(f"    output: {output[:300]!r}")
            all_ok = False
            continue
        norm = _normalize_log_record(raw)
        records[runner.name] = norm
        print(f"  [{runner.label:12s}] captured: {json.dumps(norm, sort_keys=True)}")

    if len(records) < 2:
        print("  (fewer than 2 languages produced output — skipping cross-language compare)")
        return all_ok

    mismatches = _compare_outputs(records)
    if mismatches:
        print()
        print("  MISMATCH:")
        for m in mismatches:
            print(m)
        all_ok = False
    else:
        langs = ", ".join(sorted(records))
        print(f"  MATCH: message + level agree across [{langs}]")

    return all_ok


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
            verbose=args.verbose,
            timeout=args.timeout,
        )
        if not output_ok:
            any_fail = True

    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
