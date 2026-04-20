#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Contract probe interpreter for Python.

Reads PROVIDE_CONTRACT_CASE env var, loads spec/contract_fixtures.yaml,
executes the named case step-by-step using the real public API, and emits
JSON to stdout: {"case": "<id>", "variables": {...}}.
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Anchor to repo root via VERSION file (same pattern as other probes/tests).
_REPO_ROOT = Path(__file__).resolve().parent
while not (_REPO_ROOT / "VERSION").exists():
    _REPO_ROOT = _REPO_ROOT.parent

sys.path.insert(0, str(_REPO_ROOT / "src"))

import yaml  # noqa: E402

from provide.telemetry import (  # noqa: E402
    bind_context,
    get_logger,
    get_runtime_status,
    register_secret_pattern,
    get_trace_context,
    setup_telemetry,
    shutdown_telemetry,
)
from provide.telemetry.config import (  # noqa: E402
    LoggingConfig,
    SamplingConfig,
    TelemetryConfig,
)
from provide.telemetry.propagation import (  # noqa: E402
    bind_propagation_context,
    clear_propagation_context,
    extract_w3c_context,
)

# Capture stream: replaces sys.stderr BEFORE setup so structlog's handler
# binds to it.  We can reset its contents between emit_log calls.
_capture_stream = io.StringIO()
_real_stderr = sys.stderr


# ---------------------------------------------------------------------------
# Override mapping: contract YAML key -> TelemetryConfig construction
# ---------------------------------------------------------------------------


def _build_config(overrides: dict[str, Any]) -> TelemetryConfig:
    """Translate cross-language override keys into a TelemetryConfig."""
    kwargs: dict[str, Any] = {}
    if "serviceName" in overrides:
        kwargs["service_name"] = overrides["serviceName"]
    if "environment" in overrides:
        kwargs["environment"] = overrides["environment"]

    # Sampling overrides — negative values should raise ConfigurationError.
    sampling_kwargs: dict[str, Any] = {}
    if "samplingLogsRate" in overrides:
        sampling_kwargs["logs_rate"] = float(overrides["samplingLogsRate"])
    if "samplingTracesRate" in overrides:
        sampling_kwargs["traces_rate"] = float(overrides["samplingTracesRate"])
    if sampling_kwargs:
        kwargs["sampling"] = SamplingConfig(**sampling_kwargs)

    # Always emit JSON to stderr so capture_log can parse it.
    kwargs.setdefault("logging", LoggingConfig(fmt="json"))
    return TelemetryConfig(**kwargs)


# ---------------------------------------------------------------------------
# Operation handlers
# ---------------------------------------------------------------------------


def _op_setup(step: dict[str, Any], _variables: dict[str, object]) -> None:
    # Replace sys.stderr so structlog's StreamHandler binds to our capture stream.
    sys.stderr = _capture_stream
    overrides = step.get("overrides")
    if overrides:
        setup_telemetry(_build_config(overrides))
    else:
        setup_telemetry(TelemetryConfig(logging=LoggingConfig(fmt="json")))


def _op_setup_invalid(step: dict[str, Any], variables: dict[str, object]) -> None:
    into = step["into"]
    try:
        setup_telemetry(_build_config(step.get("overrides", {})))
        variables[into] = {"raised": False, "error": ""}
    except Exception as exc:
        variables[into] = {"raised": True, "error": str(exc)}


def _op_shutdown(_step: dict[str, Any], _variables: dict[str, object]) -> None:
    shutdown_telemetry()


def _op_bind_propagation(step: dict[str, Any], _variables: dict[str, object]) -> None:
    traceparent = step.get("traceparent", "")
    baggage = step.get("baggage")
    # Build ASGI-style scope with raw headers.
    headers: list[tuple[bytes, bytes]] = []
    if traceparent:
        headers.append((b"traceparent", traceparent.encode()))
    if baggage:
        headers.append((b"baggage", baggage.encode()))
    scope: dict[str, Any] = {"type": "http", "headers": headers}
    ctx = extract_w3c_context(scope)
    bind_propagation_context(ctx)


def _op_clear_propagation(_step: dict[str, Any], _variables: dict[str, object]) -> None:
    clear_propagation_context()


def _op_get_trace_context(step: dict[str, Any], variables: dict[str, object]) -> None:
    tc = get_trace_context()
    variables[step["into"]] = {
        "trace_id": tc["trace_id"] or "",
        "span_id": tc["span_id"] or "",
    }


def _op_bind_context(step: dict[str, Any], _variables: dict[str, object]) -> None:
    bind_context(**step["fields"])


def _op_register_secret_pattern(step: dict[str, Any], _variables: dict[str, object]) -> None:
    register_secret_pattern(step["name"], re.compile(step["pattern"]))


def _op_emit_log(step: dict[str, Any], _variables: dict[str, object]) -> None:
    # Reset capture buffer before emitting.
    _capture_stream.truncate(0)
    _capture_stream.seek(0)
    # structlog uses 'event' as the first positional arg; strip it from fields
    # to avoid duplicate keyword argument errors.
    fields = {k: v for k, v in step.get("fields", {}).items() if k != "event"}
    get_logger("contract").info(step["message"], **fields)


def _op_capture_log(step: dict[str, Any], variables: dict[str, object]) -> None:
    output = _capture_stream.getvalue()
    record: dict[str, object] = {}
    # Take the last JSON line from captured stderr.
    for line in reversed(output.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            record = json.loads(line)
            break
    # Normalise: ensure trace_id / span_id / baggage keys have string defaults.
    for key in ("trace_id", "span_id", "message"):
        record.setdefault(key, "")
    variables[step["into"]] = record


def _op_get_runtime_status(step: dict[str, Any], variables: dict[str, object]) -> None:
    status = get_runtime_status()
    variables[step["into"]] = {
        "active": bool(status["setup_done"]),
        "service_name": _get_service_name(),
    }


def _get_service_name() -> str:
    """Read the active config's service_name via runtime module."""
    from provide.telemetry.runtime import get_runtime_config

    cfg = get_runtime_config()
    return cfg.service_name


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_DISPATCH: dict[str, Any] = {
    "setup": _op_setup,
    "setup_invalid": _op_setup_invalid,
    "shutdown": _op_shutdown,
    "bind_propagation": _op_bind_propagation,
    "clear_propagation": _op_clear_propagation,
    "get_trace_context": _op_get_trace_context,
    "bind_context": _op_bind_context,
    "register_secret_pattern": _op_register_secret_pattern,
    "emit_log": _op_emit_log,
    "capture_log": _op_capture_log,
    "get_runtime_status": _op_get_runtime_status,
}


def main() -> int:
    case_id = os.environ["PROVIDE_CONTRACT_CASE"]
    fixtures_path = _REPO_ROOT / "spec" / "contract_fixtures.yaml"
    with open(fixtures_path) as f:
        fixtures = yaml.safe_load(f)

    cases = fixtures["contract_cases"]
    if case_id not in cases:
        print(json.dumps({"error": f"unknown case: {case_id}"}), file=_real_stderr)
        return 1

    case = cases[case_id]
    variables: dict[str, object] = {}

    for step in case["steps"]:
        op = step["op"]
        handler = _DISPATCH.get(op)
        if handler is None:
            print(json.dumps({"error": f"unknown op: {op}"}), file=_real_stderr)
            return 1
        handler(step, variables)

    print(json.dumps({"case": case_id, "variables": variables}, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)
