#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stderr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from provide.telemetry import (
    get_logger,
    get_runtime_config,
    get_runtime_status,
    reconfigure_telemetry,
    set_trace_context,
    setup_telemetry,
    shutdown_telemetry,
)

TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
SPAN_ID = "b7ad6b7169203331"


def _extract_json_line(output: str) -> dict[str, object]:
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise RuntimeError(f"no JSON object found in output: {output!r}")


def _capture_record(message: str) -> dict[str, object]:
    buf = io.StringIO()
    with redirect_stderr(buf):
        set_trace_context(TRACE_ID, SPAN_ID)
        get_logger("probe").info(message)
    return _extract_json_line(buf.getvalue())


def _setup_and_capture_record(message: str) -> tuple[dict[str, object], dict[str, object]]:
    buf = io.StringIO()
    with redirect_stderr(buf):
        setup_telemetry()
        status = get_runtime_status()
        set_trace_context(TRACE_ID, SPAN_ID)
        get_logger("probe").info(message)
    return status, _extract_json_line(buf.getvalue())


def _case_lazy_init_logger() -> dict[str, object]:
    return {"case": "lazy_init_logger", "record": _capture_record("log.output.parity")}


def _case_lazy_logger_shutdown_re_setup() -> dict[str, object]:
    first = _capture_record("log.output.parity")
    shutdown_telemetry()
    second = get_runtime_status()
    os.environ["PROVIDE_TELEMETRY_SERVICE_NAME"] = "probe-restarted"
    os.environ["PROVIDE_TELEMETRY_ENV"] = "parity-restarted"
    os.environ["PROVIDE_TELEMETRY_VERSION"] = "9.9.9"
    third, restarted = _setup_and_capture_record("log.output.restart")
    shutdown_telemetry()
    return {
        "case": "lazy_logger_shutdown_re_setup",
        "first_logger_emitted": first.get("message") == "log.output.parity",
        "shutdown_cleared_setup": not bool(second["setup_done"]),
        "shutdown_cleared_providers": not any(second["providers"].values()),
        "shutdown_fallback_all": all(second["fallback"].values()),
        "re_setup_done": bool(third["setup_done"]),
        "second_logger_uses_fresh_config": restarted.get("service") == "probe-restarted"
        and restarted.get("env") == "parity-restarted"
        and restarted.get("version") == "9.9.9",
    }


def _case_strict_schema_rejection() -> dict[str, object]:
    record = _capture_record("Bad.Event.Ok")
    shutdown_telemetry()
    return {
        "case": "strict_schema_rejection",
        "emitted": True,
        "schema_error": "_schema_error" in record,
    }


def _case_strict_event_name_only() -> dict[str, object]:
    record = _capture_record("Bad.Event.Ok")
    shutdown_telemetry()
    return {
        "case": "strict_event_name_only",
        "emitted": True,
        "schema_error": "_schema_error" in record,
    }


def _case_required_keys_rejection() -> dict[str, object]:
    record = _capture_record("user.auth.ok")
    shutdown_telemetry()
    return {
        "case": "required_keys_rejection",
        "emitted": True,
        "schema_error": "_schema_error" in record,
    }


def _case_invalid_config() -> dict[str, object]:
    try:
        setup_telemetry()
    except Exception:
        return {"case": "invalid_config", "raised": True}
    return {"case": "invalid_config", "raised": False}


def _case_fail_open_exporter_init() -> dict[str, object]:
    setup_telemetry()
    status = get_runtime_status()
    shutdown_telemetry()
    return {
        "case": "fail_open_exporter_init",
        "setup_done": bool(status["setup_done"]),
        "providers_cleared": not any(status["providers"].values()),
        "fallback_all": all(status["fallback"].values()),
    }


def _case_signal_enablement() -> dict[str, object]:
    setup_telemetry()
    status = get_runtime_status()
    shutdown_telemetry()
    signals = status["signals"]
    return {
        "case": "signal_enablement",
        "setup_done": bool(status["setup_done"]),
        "logs_enabled": bool(signals["logs"]),
        "traces_enabled": bool(signals["traces"]),
        "metrics_enabled": bool(signals["metrics"]),
    }


def _case_per_signal_logs_endpoint() -> dict[str, object]:
    setup_telemetry()
    status = get_runtime_status()
    shutdown_telemetry()
    providers = status["providers"]
    return {
        "case": "per_signal_logs_endpoint",
        "setup_done": bool(status["setup_done"]),
        "logs_provider": bool(providers["logs"]),
        "traces_provider": bool(providers["traces"]),
        "metrics_provider": bool(providers["metrics"]),
    }


def _case_provider_identity_reconfigure() -> dict[str, object]:
    setup_telemetry()
    before = get_runtime_status()
    service_before = get_runtime_config().service_name
    target = get_runtime_config()
    target.service_name = f"{service_before}-renamed"
    raised = False
    try:
        reconfigure_telemetry(target)
    except Exception:
        raised = True
    config_preserved = get_runtime_config().service_name == service_before
    shutdown_telemetry()
    return {
        "case": "provider_identity_reconfigure",
        "providers_active": any(before["providers"].values()),
        "raised": raised,
        "config_preserved": config_preserved,
    }


def _case_shutdown_re_setup() -> dict[str, object]:
    setup_telemetry()
    first = get_runtime_status()
    shutdown_telemetry()
    second = get_runtime_status()
    setup_telemetry()
    third = get_runtime_status()
    shutdown_telemetry()
    return {
        "case": "shutdown_re_setup",
        "first_setup_done": bool(first["setup_done"]),
        "shutdown_cleared_setup": not bool(second["setup_done"]),
        "shutdown_cleared_providers": not any(second["providers"].values()),
        "shutdown_fallback_all": all(second["fallback"].values()),
        "re_setup_done": bool(third["setup_done"]),
        "signals_match": first["signals"] == third["signals"],
        "providers_match": first["providers"] == third["providers"],
    }


def main() -> int:
    case = os.environ["PROVIDE_PARITY_PROBE_CASE"]
    result = {
        "lazy_init_logger": _case_lazy_init_logger,
        "lazy_logger_shutdown_re_setup": _case_lazy_logger_shutdown_re_setup,
        "strict_schema_rejection": _case_strict_schema_rejection,
        "strict_event_name_only": _case_strict_event_name_only,
        "required_keys_rejection": _case_required_keys_rejection,
        "invalid_config": _case_invalid_config,
        "fail_open_exporter_init": _case_fail_open_exporter_init,
        "signal_enablement": _case_signal_enablement,
        "per_signal_logs_endpoint": _case_per_signal_logs_endpoint,
        "provider_identity_reconfigure": _case_provider_identity_reconfigure,
        "shutdown_re_setup": _case_shutdown_re_setup,
    }[case]()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)
