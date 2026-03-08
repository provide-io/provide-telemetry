# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Tracing facade."""

from undef.telemetry.tracing.context import get_trace_context, set_trace_context
from undef.telemetry.tracing.decorators import trace
from undef.telemetry.tracing.provider import get_tracer, setup_tracing, shutdown_tracing, tracer

__all__ = [
    "get_trace_context",
    "get_tracer",
    "set_trace_context",
    "setup_tracing",
    "shutdown_tracing",
    "trace",
    "tracer",
]
