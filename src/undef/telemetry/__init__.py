# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Public API for undef telemetry."""

from importlib.metadata import PackageNotFoundError, version

from undef.telemetry.asgi import TelemetryMiddleware, bind_websocket_context
from undef.telemetry.logger import bind_context, clear_context, get_logger, logger, unbind_context
from undef.telemetry.metrics import counter, gauge, get_meter, histogram
from undef.telemetry.setup import setup_telemetry, shutdown_telemetry
from undef.telemetry.tracing import get_trace_context, get_tracer, set_trace_context, trace, tracer

try:
    __version__ = version("undef-telemetry")
except (PackageNotFoundError, TypeError):
    __version__ = "0.0.0"

__all__ = [
    "TelemetryMiddleware",
    "__version__",
    "bind_context",
    "bind_websocket_context",
    "clear_context",
    "counter",
    "gauge",
    "get_logger",
    "get_meter",
    "get_trace_context",
    "get_tracer",
    "histogram",
    "logger",
    "set_trace_context",
    "setup_telemetry",
    "shutdown_telemetry",
    "trace",
    "tracer",
    "unbind_context",
]
