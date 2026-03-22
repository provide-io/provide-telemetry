# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Logging facade."""

from undef.telemetry.logger.context import bind_context, clear_context, get_context, unbind_context
from undef.telemetry.logger.core import configure_logging, get_logger, is_debug_enabled, is_trace_enabled, logger

__all__ = [
    "bind_context",
    "clear_context",
    "configure_logging",
    "get_context",
    "get_logger",
    "is_debug_enabled",
    "is_trace_enabled",
    "logger",
    "unbind_context",
]
