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

from provide.telemetry import (  # noqa: E402
    get_logger,
    get_runtime_status,
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


def _case_lazy_init_logger() -> dict[str, object]:
    return {"case": "lazy_init_logger", "record": _capture_record("log.output.parity")}


def _case_strict_schema_rejection() -> dict[str, object]:
    record = _capture_record("Bad.Event.Ok")
    shutdown_telemetry()
    return {
        "case": "strict_schema_rejection",
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
        "re_setup_done": bool(third["setup_done"]),
        "signals_match": first["signals"] == third["signals"],
        "providers_match": first["providers"] == third["providers"],
    }


def main() -> int:
    case = os.environ["PROVIDE_PARITY_PROBE_CASE"]
    result = {
        "lazy_init_logger": _case_lazy_init_logger,
        "strict_schema_rejection": _case_strict_schema_rejection,
        "required_keys_rejection": _case_required_keys_rejection,
        "invalid_config": _case_invalid_config,
        "fail_open_exporter_init": _case_fail_open_exporter_init,
        "signal_enablement": _case_signal_enablement,
        "shutdown_re_setup": _case_shutdown_re_setup,
    }[case]()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)
