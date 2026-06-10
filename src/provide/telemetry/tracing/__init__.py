# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tracing facade."""

from provide.telemetry.tracing.context import get_trace_context, set_trace_context
from provide.telemetry.tracing.decorators import trace
from provide.telemetry.tracing.provider import get_tracer, setup_tracing, shutdown_tracing, tracer
from provide.telemetry.tracing.span import record_exception, set_attrs, span

__all__ = [
    "get_trace_context",
    "get_tracer",
    "record_exception",
    "set_attrs",
    "set_trace_context",
    "setup_tracing",
    "shutdown_tracing",
    "span",
    "trace",
    "tracer",
]
