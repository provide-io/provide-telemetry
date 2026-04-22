# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Runtime-probe helpers for behavioral parity checks.

Split out of ``parity_probe_support`` to keep that file under the 500-LOC
ceiling. Imports the shared ProbeRunner type and small utilities from the
parent module — the parent does NOT import from this module to avoid cycles.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from parity_probe_support import ProbeRunner


class SharedHelpers(NamedTuple):
    """Typed view of the shared symbols pulled from parity_probe_support.

    Replaces a previous positional 7-tuple — accessing fields by name avoids
    silent breakage when entries are added or reordered.
    """

    ProbeRunner: type[ProbeRunner]
    OTEL_REQUIRED_CASE_IDS: frozenset[str]
    compare_outputs: object
    extract_json_line: object
    has_otel_stack: object
    normalize_log_record: object
    probe_env: object


def _from_module(mod: object) -> SharedHelpers:
    return SharedHelpers(
        ProbeRunner=mod.ProbeRunner,  # type: ignore[attr-defined]
        OTEL_REQUIRED_CASE_IDS=mod._OTEL_REQUIRED_CASE_IDS,  # type: ignore[attr-defined]
        compare_outputs=mod._compare_outputs,  # type: ignore[attr-defined]
        extract_json_line=mod._extract_json_line,  # type: ignore[attr-defined]
        has_otel_stack=mod._has_otel_stack,  # type: ignore[attr-defined]
        normalize_log_record=mod._normalize_log_record,  # type: ignore[attr-defined]
        probe_env=mod._probe_env,  # type: ignore[attr-defined]
    )


def _shared() -> SharedHelpers:
    """Lazy lookup of shared helpers from parity_probe_support.

    Returns a typed ``SharedHelpers`` view; callers access fields by name
    (e.g. ``_shared().ProbeRunner``) rather than by tuple position.

    Resolution order (deterministic):
      1. The canonical ``parity_probe_support`` entry in ``sys.modules`` if
         present — matches Python's default import semantics, so existing
         callers that loaded the module canonically see no behavior change.
      2. Any module loaded under an alias (e.g. via
         ``importlib.util.spec_from_file_location`` in tooling/tests) whose
         ``__file__`` ends with ``parity_probe_support.py``. This preserves
         monkeypatches applied to the aliased module instead of triggering
         a fresh canonical import that would create a duplicate module
         instance.
      3. Fallback to a fresh canonical ``from parity_probe_support import …``.

    Preferring (1) over (2) when both are loaded avoids the ambiguity of
    "which copy wins" — callers that intentionally use an alias should not
    co-load the canonical name.
    """
    import sys

    canonical = sys.modules.get("parity_probe_support")
    if canonical is not None:
        return _from_module(canonical)

    target = "parity_probe_support.py"
    for mod in list(sys.modules.values()):
        if mod is None:
            continue
        mod_file = getattr(mod, "__file__", None)
        if mod_file and mod_file.endswith(target):
            return _from_module(mod)

    import parity_probe_support  # type: ignore[import-not-found]

    return _from_module(parity_probe_support)


def _runtime_probe_runners(repo: Path, cargo_bin: str, cargo_env: dict[str, str]) -> list[ProbeRunner]:
    ProbeRunner = _shared().ProbeRunner
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


def _runtime_probe_case_env(case_id: str) -> dict[str, str]:
    if case_id == "strict_schema_rejection":
        return {
            "PROVIDE_TELEMETRY_STRICT_SCHEMA": "true",
            "PROVIDE_TRACE_ENABLED": "false",
            "PROVIDE_METRICS_ENABLED": "false",
        }
    if case_id == "lazy_logger_shutdown_re_setup":
        return {
            "PROVIDE_TRACE_ENABLED": "false",
            "PROVIDE_METRICS_ENABLED": "false",
        }
    if case_id == "strict_event_name_only":
        return {
            "PROVIDE_TELEMETRY_STRICT_SCHEMA": "false",
            "PROVIDE_TELEMETRY_STRICT_EVENT_NAME": "true",
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
    if case_id == "per_signal_logs_endpoint":
        return {
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://127.0.0.1:4318/v1/logs",
            "PROVIDE_TRACE_ENABLED": "false",
            "PROVIDE_METRICS_ENABLED": "false",
        }
    if case_id == "provider_identity_reconfigure":
        return {
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318",
        }
    if case_id == "shutdown_re_setup":
        return {
            "PROVIDE_TRACE_ENABLED": "false",
            "PROVIDE_METRICS_ENABLED": "false",
        }
    return {}


def _run_runtime_probe(
    runner: ProbeRunner,
    case_id: str,
    probe_env: dict[str, str],
    *,
    timeout: int = 60,
) -> tuple[str, str]:
    probe_env_fn = _shared().probe_env
    env = {
        **os.environ,
        **probe_env_fn(probe_env),  # type: ignore[operator]
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


def _load_runtime_probe_fixtures(fixtures_path: Path) -> dict[str, object]:
    import yaml  # lazy: allow importing without PyYAML installed

    return yaml.safe_load(fixtures_path.read_text(encoding="utf-8"))


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
    helpers = _shared()
    _OTEL_REQUIRED_CASE_IDS = helpers.OTEL_REQUIRED_CASE_IDS
    _compare_outputs = helpers.compare_outputs
    _extract_json_line = helpers.extract_json_line
    _has_otel_stack = helpers.has_otel_stack
    _normalize_log_record = helpers.normalize_log_record
    runners = [r for r in _runtime_probe_runners(repo, cargo_bin, cargo_env) if r.name in selected]
    fixtures = _load_runtime_probe_fixtures(fixtures_path)
    cases = fixtures.get("cases", [])

    # Fail early with a clear install hint if OTel-required cases are in the fixture
    # list, the Python runner is selected, and the opentelemetry-sdk[otlp] extra is
    # not installed.  Guard is skipped when Python is not in `selected` so that
    # subset runs (e.g. --lang go,rust,typescript) are unaffected.
    otel_case_ids = {str(c["id"]) for c in cases} & _OTEL_REQUIRED_CASE_IDS
    if "python" in selected and otel_case_ids and not _has_otel_stack():
        raise RuntimeError(
            f"Runtime probe cases {sorted(otel_case_ids)} require the "
            "opentelemetry-sdk[otlp] extra — run: uv sync --extra otel"
        )

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

        mismatches_other: list[str] = []
        for lang, summary in summaries.items():
            for field_name, value in expected.items():
                if summary.get(field_name) != value:
                    mismatches_other.append(
                        f"  {lang}: field '{field_name}' expected {value!r}, got {summary.get(field_name)!r}"
                    )
        if mismatches_other:
            print("    MISMATCH:")
            for mismatch in mismatches_other:
                print(mismatch)
            all_ok = False
        else:
            print("    MATCH")

    return all_ok
