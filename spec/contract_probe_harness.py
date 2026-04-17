#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Contract probe DSL harness — step-based cross-language parity checks."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Env vars injected into every contract probe process.
_CONTRACT_PROBE_ENV: dict[str, str] = {
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

# Bracket-notation regex: matches e.g. last_log["baggage.userId"]
_BRACKET_RE = re.compile(r'([^"\[\]]+)\["([^"]+)"\]')


@dataclass
class _ContractProbeRunner:
    """How to invoke a contract probe for one language."""

    name: str
    label: str
    cmd: list[str]
    cwd: Path
    env_extra: dict[str, str] = field(default_factory=dict)


def _contract_probe_runners(
    repo: Path,
    cargo_bin: str,
    cargo_env: dict[str, str],
) -> list[_ContractProbeRunner]:
    """Return probe runners for the contract probe in each language."""
    probes = repo / "spec" / "probes"
    return [
        _ContractProbeRunner(
            name="python",
            label="Python",
            cmd=[sys.executable, str(probes / "contract_probe_python.py")],
            cwd=repo,
        ),
        _ContractProbeRunner(
            name="typescript",
            label="TypeScript",
            cmd=["npx", "tsx", str(probes / "contract_probe_typescript.ts")],
            cwd=repo / "typescript",
            env_extra={"NODE_PATH": str(repo / "typescript" / "node_modules")},
        ),
        _ContractProbeRunner(
            name="go",
            label="Go",
            cmd=["go", "run", str(probes / "contract_probe_go" / "main.go")],
            cwd=repo / "go",
        ),
        _ContractProbeRunner(
            name="rust",
            label="Rust",
            cmd=[cargo_bin, "--locked", "run", "--example", "contract_probe", "--quiet"],
            cwd=repo / "rust",
            env_extra={**cargo_env},
        ),
    ]


def _resolve_path(variables: dict[str, object], path: str) -> object | None:
    """Resolve a dotted/bracket path against the variables dict.

    Rules:
    - ``a.b.c`` -> variables["a"]["b"]["c"]
    - ``a["b.c"]`` -> variables["a"]["b.c"]  (bracket key is literal)
    - Returns None if any key is missing or intermediary is not a dict.
    """
    # Check for bracket notation first: var["literal.key"]
    m = _BRACKET_RE.match(path)
    if m:
        var_path, literal_key = m.group(1), m.group(2)
        obj = _walk_dotted(variables, var_path)
        if not isinstance(obj, dict):
            return None
        return obj.get(literal_key)
    return _walk_dotted(variables, path)


def _walk_dotted(variables: dict[str, object], dotted: str) -> object | None:
    """Walk a simple dotted path like ``a.b.c``."""
    parts = dotted.split(".")
    current: object = variables
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)  # type: ignore[union-attr]
        if current is None:
            return None
    return current


def _run_contract_probe(
    runner: _ContractProbeRunner,
    case_id: str,
    *,
    timeout: int = 90,
) -> tuple[dict[str, object] | None, str]:
    """Run a contract probe for *case_id*. Returns (parsed_json, error)."""
    env = {
        **os.environ,
        **_CONTRACT_PROBE_ENV,
        "PROVIDE_CONTRACT_CASE": case_id,
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
    except FileNotFoundError:
        return None, f"{runner.label}: command not found ({runner.cmd[0]})"
    except subprocess.TimeoutExpired:
        return None, f"{runner.label}: timed out after {timeout}s"

    combined = (proc.stdout + proc.stderr).strip()
    if proc.returncode != 0:
        snippet = combined[:300] if combined else f"exit code {proc.returncode}"
        return None, f"{runner.label}: probe failed — {snippet}"

    # Find the JSON object line in stdout
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    return parsed, ""
            except json.JSONDecodeError:
                continue
    return None, f"{runner.label}: no valid JSON object in stdout"


def _collect_all_paths(variables: dict[str, object], prefix: str = "") -> list[str]:
    """Enumerate all leaf dotted paths in a nested dict."""
    paths: list[str] = []
    for key, value in variables.items():
        full = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            paths.extend(_collect_all_paths(value, full))
        else:
            paths.append(full)
    return paths


def run_contract_cases(
    repo: Path,
    selected: set[str],
    cargo_bin: str,
    cargo_env: dict[str, str],
) -> bool:
    """Run contract DSL cases across all languages. Returns True if all pass."""
    import yaml  # lazy: allow importing without PyYAML installed

    fixtures_path = repo / "spec" / "contract_fixtures.yaml"
    fixtures = yaml.safe_load(fixtures_path.read_text(encoding="utf-8"))
    cases: dict[str, dict[str, object]] = fixtures.get("contract_cases", {})
    if not cases:
        print("  WARNING: no contract_cases found in fixtures")
        return True

    runners = _contract_probe_runners(repo, cargo_bin, cargo_env)
    # Filter to selected languages if non-empty
    if selected:
        runners = [r for r in runners if r.name in selected]

    all_ok = True
    print()
    print("── Contract parity probes ─────────────────────────")

    for case_id, case_def in cases.items():
        description = case_def.get("description", "")
        expect: dict[str, object] = case_def.get("expect", {})  # type: ignore[assignment]
        print(f"  case={case_id}: {description}")

        # Run each language's probe
        results: dict[str, dict[str, object]] = {}
        case_ok = True
        for runner in runners:
            parsed, err = _run_contract_probe(runner, case_id)
            if err:
                print(f"    [{runner.label:12s}] PROBE ERROR: {err}")
                case_ok = False
                continue
            # Validate output shape
            if not isinstance(parsed, dict) or "case" not in parsed or "variables" not in parsed:
                print(f"    [{runner.label:12s}] INVALID: missing 'case' or 'variables' keys")
                case_ok = False
                continue
            if parsed["case"] != case_id:
                print(f"    [{runner.label:12s}] INVALID: case mismatch {parsed['case']!r} != {case_id!r}")
                case_ok = False
                continue
            variables = parsed["variables"]
            if not isinstance(variables, dict):
                print(f"    [{runner.label:12s}] INVALID: 'variables' is not a dict")
                case_ok = False
                continue
            results[runner.name] = variables

        if not case_ok:
            all_ok = False

        if len(results) < 1:
            print("    SKIP (no language produced valid output)")
            continue

        # Check expectations
        mismatches: list[str] = []
        for path, expected_value in expect.items():
            for lang, variables in results.items():
                actual = _resolve_path(variables, path)
                if actual != expected_value:
                    mismatches.append(f"    {lang}: {path} expected {expected_value!r}, got {actual!r}")

        # Cross-compare: collect all variable paths present in 2+ languages
        if len(results) >= 2:
            all_lang_paths: dict[str, dict[str, object]] = {}
            for lang, variables in results.items():
                for p in _collect_all_paths(variables):
                    all_lang_paths.setdefault(p, {})[lang] = _resolve_path(variables, p)
            for p, lang_values in all_lang_paths.items():
                if len(lang_values) < 2:
                    continue
                unique_vals = set()
                for v in lang_values.values():
                    unique_vals.add(json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else repr(v))
                if len(unique_vals) > 1:
                    detail = ", ".join(f"{lang}={v!r}" for lang, v in sorted(lang_values.items()))
                    mismatches.append(f"    cross-compare divergence on '{p}': {detail}")

        if mismatches:
            print("    FAIL:")
            for m in mismatches:
                print(m)
            all_ok = False
        else:
            langs = ", ".join(sorted(results))
            print(f"    PASS [{langs}]")

    return all_ok
