#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Probe helpers for behavioral parity checks."""

from __future__ import annotations

# Contract probe harness lives in spec/contract_probe_harness.py to stay under 500 LOC.
# Re-export run_contract_cases for callers that import from this module.
import importlib.util as _ilu
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_harness_spec = _ilu.spec_from_file_location(
    "contract_probe_harness", Path(__file__).parent / "contract_probe_harness.py"
)
assert _harness_spec is not None and _harness_spec.loader is not None
_harness_mod = _ilu.module_from_spec(_harness_spec)
sys.modules["contract_probe_harness"] = _harness_mod  # register before exec for dataclass compat
_harness_spec.loader.exec_module(_harness_mod)
run_contract_cases = _harness_mod.run_contract_cases  # type: ignore[attr-defined]

# Env vars injected into every probe process (matches spec/behavioral_fixtures.yaml).
_PROBE_ENV_DEFAULTS: dict[str, str] = {
    "PROVIDE_LOG_FORMAT": "json",
    "PROVIDE_TELEMETRY_SERVICE_NAME": "probe",
    "PROVIDE_TELEMETRY_ENV": "parity",
    "PROVIDE_TELEMETRY_VERSION": "1.2.3",
    "PROVIDE_LOG_LEVEL": "INFO",
    "PROVIDE_LOG_INCLUDE_TIMESTAMP": "false",
    "PROVIDE_LOG_INCLUDE_CALLER": "false",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "",
    "OTEL_EXPORTER_OTLP_HEADERS": "",
    "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "",
    "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "",
    "OTEL_EXPORTER_OTLP_TRACES_HEADERS": "",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "",
    "OTEL_EXPORTER_OTLP_METRICS_HEADERS": "",
}

# Canonical field renames: {raw_field: canonical_field}.
# Applied before comparison so all languages share the same key names.
_FIELD_RENAMES: dict[str, str] = {
    "msg": "message",
    "message": "message",
    "time": "timestamp",
    "target": "logger_name",
    "name": "logger_name",
    "service.name": "service",
    "service.env": "env",
    "service.version": "version",
    "trace.id": "trace_id",
    "span.id": "span_id",
}

_NOISE_FIELDS: frozenset[str] = frozenset({"pid", "hostname", "v", "event"})
_PINO_LEVELS: dict[int, str] = {10: "TRACE", 20: "DEBUG", 30: "INFO", 40: "WARN", 50: "ERROR", 60: "FATAL"}
_ISO8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
_VALID_LEVELS: frozenset[str] = frozenset({"TRACE", "DEBUG", "INFO", "WARN", "WARNING", "ERROR", "CRITICAL"})
_TRACE_ID_RE: re.Pattern[str] = re.compile(r"^[0-9a-f]{32}$")
_SPAN_ID_RE: re.Pattern[str] = re.compile(r"^[0-9a-f]{16}$")


@dataclass
class ProbeRunner:
    """How to invoke the emit probe for one language."""

    name: str
    label: str
    cmd: list[str]
    cwd: Path
    env_extra: dict[str, str] = field(default_factory=dict)


def _probe_runners(repo: Path, cargo_bin: str, cargo_env: dict[str, str]) -> list[ProbeRunner]:
    probes = repo / "spec" / "probes"
    return [
        ProbeRunner(
            name="python",
            label="Python",
            cmd=[sys.executable, str(probes / "emit_log_python.py")],
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
            env_extra={"NODE_PATH": str(repo / "typescript" / "node_modules")},
        ),
        ProbeRunner(
            name="rust",
            label="Rust",
            cmd=[cargo_bin, "--locked", "run", "--example", "emit_log_probe", "--quiet"],
            cwd=repo / "rust",
            env_extra={**cargo_env},
        ),
    ]


def _runtime_probe_runners(repo: Path, cargo_bin: str, cargo_env: dict[str, str]) -> list[ProbeRunner]:
    probes = repo / "spec" / "probes"
    return [
        ProbeRunner(
            name="python",
            label="Python",
            cmd=[sys.executable, str(probes / "runtime_probe_python.py")],
            cwd=repo,
        ),
        ProbeRunner(
            name="go",
            label="Go",
            cmd=["go", "run", str(probes / "runtime_probe_go" / "main.go")],
            cwd=repo / "go",
        ),
        ProbeRunner(
            name="typescript",
            label="TypeScript",
            cmd=["npx", "tsx", str(probes / "runtime_probe_typescript.ts")],
            cwd=repo / "typescript",
            env_extra={"NODE_PATH": str(repo / "typescript" / "node_modules")},
        ),
        ProbeRunner(
            name="rust",
            label="Rust",
            cmd=[cargo_bin, "--locked", "run", "--features", "otel", "--example", "runtime_probe", "--quiet"],
            cwd=repo / "rust",
            env_extra={**cargo_env},
        ),
    ]


def _normalize_log_record(raw: dict[str, object]) -> dict[str, object]:
    """Apply canonical renames, strip noise, normalise level to uppercase string."""
    result: dict[str, object] = {}
    for k, v in raw.items():
        canonical = _FIELD_RENAMES.get(k, k)
        if k not in _NOISE_FIELDS:
            result[canonical] = v
    level = result.get("level")
    if isinstance(level, int):
        result["level"] = _PINO_LEVELS.get(level, str(level))
    elif isinstance(level, str):
        result["level"] = level.upper()
    return result


def _probe_env(probe_env: dict[str, str]) -> dict[str, str]:
    return {**_PROBE_ENV_DEFAULTS, **probe_env}


def _run_probe(runner: ProbeRunner, probe_env: dict[str, str], *, timeout: int = 60) -> tuple[str, str]:
    """Run probe; return (combined_output, error_message_or_empty)."""
    env = {**os.environ, **_probe_env(probe_env), **runner.env_extra}
    try:
        proc = subprocess.run(  # noqa: S603
            runner.cmd,
            capture_output=True,
            text=True,
            cwd=runner.cwd,
            env=env,
            timeout=timeout,
            check=False,
        )
        combined = (proc.stdout + proc.stderr).strip()
        if proc.returncode != 0 and not combined:
            return "", f"exit code {proc.returncode}: {proc.stderr.strip()[:200]}"
        return combined, ""
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return "", str(exc)


def _run_runtime_probe(
    runner: ProbeRunner,
    case_id: str,
    probe_env: dict[str, str],
    *,
    timeout: int = 60,
) -> tuple[str, str]:
    env = {
        **os.environ,
        **_probe_env(probe_env),
        **_runtime_probe_case_env(case_id),
        "PROVIDE_PARITY_PROBE_CASE": case_id,
        **runner.env_extra,
    }
    try:
        proc = subprocess.run(  # noqa: S603
            runner.cmd,
            capture_output=True,
            text=True,
            cwd=runner.cwd,
            env=env,
            timeout=timeout,
            check=False,
        )
        combined = (proc.stdout + proc.stderr).strip()
        if proc.returncode != 0 and not combined:
            return "", f"exit code {proc.returncode}: {proc.stderr.strip()[:200]}"
        if proc.returncode != 0:
            return "", combined[:500]
        return combined, ""
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return "", str(exc)


def _extract_json_line(output: str) -> dict[str, object] | None:
    """Find and parse the first line in output that looks like a JSON object."""
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def _runtime_probe_case_env(case_id: str) -> dict[str, str]:
    if case_id == "strict_schema_rejection":
        return {
            "PROVIDE_TELEMETRY_STRICT_SCHEMA": "true",
            "PROVIDE_TRACE_ENABLED": "false",
            "PROVIDE_METRICS_ENABLED": "false",
        }
    if case_id == "required_keys_rejection":
        return {
            "PROVIDE_TELEMETRY_STRICT_SCHEMA": "false",
            "PROVIDE_TELEMETRY_REQUIRED_KEYS": "request_id",
            "PROVIDE_TRACE_ENABLED": "false",
            "PROVIDE_METRICS_ENABLED": "false",
        }
    if case_id == "invalid_config":
        return {"PROVIDE_LOG_INCLUDE_TIMESTAMP": "definitely-not-a-bool"}
    if case_id == "fail_open_exporter_init":
        return {
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://[",
            "OTEL_EXPORTER_OTLP_PROTOCOL": "definitely-invalid",
        }
    if case_id == "signal_enablement":
        return {
            "PROVIDE_TRACE_ENABLED": "false",
            "PROVIDE_METRICS_ENABLED": "false",
        }
    if case_id == "shutdown_re_setup":
        return {
            "PROVIDE_TRACE_ENABLED": "false",
            "PROVIDE_METRICS_ENABLED": "false",
        }
    return {}


def _compare_outputs(records: dict[str, dict[str, object]]) -> list[str]:
    """Cross-compare required and optional fields across all language records."""
    mismatches: list[str] = []
    for field_name in ("message", "level"):
        values = {lang: rec.get(field_name) for lang, rec in records.items()}
        if len({v for v in values.values() if v is not None}) > 1:
            mismatches.append(
                f"  field '{field_name}' differs: " + ", ".join(f"{lang}={v!r}" for lang, v in sorted(values.items()))
            )
    for lang, rec in records.items():
        lvl = rec.get("level")
        if lvl is not None and str(lvl) not in _VALID_LEVELS:
            mismatches.append(f"  {lang}: 'level' has unexpected value: {lvl!r}")
    for field_name in ("service", "env", "version", "logger_name", "trace_id", "span_id"):
        values = {lang: rec.get(field_name) for lang, rec in records.items()}
        present = {lang: value for lang, value in values.items() if value is not None}
        if not present:
            continue
        missing = sorted(lang for lang, value in values.items() if value is None)
        if missing:
            mismatches.append(f"  field '{field_name}' presence differs: missing in {', '.join(missing)}")
            continue
        if len(set(present.values())) > 1:
            mismatches.append(
                f"  field '{field_name}' differs: " + ", ".join(f"{lang}={v!r}" for lang, v in sorted(present.items()))
            )
    timestamp_values = {lang: rec.get("timestamp") for lang, rec in records.items()}
    timestamp_present = {lang: value for lang, value in timestamp_values.items() if value is not None}
    if timestamp_present and len(timestamp_present) != len(records):
        missing = sorted(lang for lang, value in timestamp_values.items() if value is None)
        mismatches.append(f"  timestamp presence differs: missing in {', '.join(missing)}")
    for lang, ts in timestamp_present.items():
        if not _ISO8601_RE.match(str(ts)):
            mismatches.append(f"  {lang}: 'timestamp' is not ISO 8601: {ts!r}")
    for lang, rec in records.items():
        tid = rec.get("trace_id")
        if tid is not None and not _TRACE_ID_RE.match(str(tid)):
            mismatches.append(f"  {lang}: 'trace_id' invalid format: {tid!r}")
        sid = rec.get("span_id")
        if sid is not None and not _SPAN_ID_RE.match(str(sid)):
            mismatches.append(f"  {lang}: 'span_id' invalid format: {sid!r}")
    return mismatches


def _load_runtime_probe_fixtures(fixtures_path: Path) -> dict[str, object]:
    import yaml  # lazy: allow importing parity_probe_support without PyYAML installed

    return yaml.safe_load(fixtures_path.read_text(encoding="utf-8"))


def run_output_check(
    repo: Path,
    selected: set[str],
    cargo_bin: str,
    cargo_env: dict[str, str],
    probe_env: dict[str, str],
    *,
    verbose: bool = False,
    timeout: int = 60,
) -> bool:
    """Run output probes and compare canonical JSON fields. Returns True if all pass."""
    runners = [r for r in _probe_runners(repo, cargo_bin, cargo_env) if r.name in selected]
    records: dict[str, dict[str, object]] = {}
    all_ok = True

    print()
    print("── Log output parity ───────────────────────────────")
    for runner in runners:
        output, err = _run_probe(runner, probe_env, timeout=timeout)
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
        for mismatch in mismatches:
            print(mismatch)
        all_ok = False
    else:
        langs = ", ".join(sorted(records))
        print(f"  MATCH: canonical envelope agrees across [{langs}]")

    return all_ok


def run_runtime_probe_check(
    repo: Path,
    selected: set[str],
    cargo_bin: str,
    cargo_env: dict[str, str],
    probe_env: dict[str, str],
    fixtures_path: Path,
    *,
    timeout: int = 60,
) -> bool:
    runners = [r for r in _runtime_probe_runners(repo, cargo_bin, cargo_env) if r.name in selected]
    fixtures = _load_runtime_probe_fixtures(fixtures_path)
    cases = fixtures.get("cases", [])
    all_ok = True

    print()
    print("── Runtime parity probes ───────────────────────────")
    for case in cases:
        case_id = str(case["id"])
        kind = str(case["kind"])
        expected = dict(case["expected"])
        print(f"  case={case_id}")
        records: dict[str, dict[str, object]] = {}
        summaries: dict[str, dict[str, object]] = {}
        case_ok = True
        for runner in runners:
            output, err = _run_runtime_probe(runner, case_id, probe_env, timeout=timeout)
            if err:
                print(f"    [{runner.label:12s}] PROBE ERROR: {err}")
                case_ok = False
                continue
            raw = _extract_json_line(output)
            if raw is None:
                print(f"    [{runner.label:12s}] NO JSON LINE in output")
                case_ok = False
                continue
            summaries[runner.name] = raw
            if kind == "record":
                record = raw.get("record")
                if not isinstance(record, dict):
                    print(f"    [{runner.label:12s}] missing record payload")
                    case_ok = False
                    continue
                records[runner.name] = _normalize_log_record(record)
                print(f"    [{runner.label:12s}] {json.dumps(records[runner.name], sort_keys=True)}")
            else:
                print(f"    [{runner.label:12s}] {json.dumps(raw, sort_keys=True)}")

        if not case_ok:
            all_ok = False
            continue

        if kind == "record":
            mismatches = _compare_outputs(records)
            for field_name, value in expected.items():
                field_values = {lang: rec.get(field_name) for lang, rec in records.items()}
                if any(field_value != value for field_value in field_values.values()):
                    mismatches.append(
                        f"  field '{field_name}' does not match expected {value!r}: "
                        + ", ".join(f"{lang}={field_value!r}" for lang, field_value in sorted(field_values.items()))
                    )
            if mismatches:
                print("    MISMATCH:")
                for mismatch in mismatches:
                    print(mismatch)
                all_ok = False
            else:
                print("    MATCH")
            continue

        mismatches: list[str] = []
        for lang, summary in summaries.items():
            for field_name, value in expected.items():
                if summary.get(field_name) != value:
                    mismatches.append(
                        f"  {lang}: field '{field_name}' expected {value!r}, got {summary.get(field_name)!r}"
                    )
        if mismatches:
            print("    MISMATCH:")
            for mismatch in mismatches:
                print(mismatch)
            all_ok = False
        else:
            print("    MATCH")

    return all_ok
