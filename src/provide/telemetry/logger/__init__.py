# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Logging facade."""

from provide.telemetry.logger.context import bind_context, clear_context, get_context, unbind_context
from provide.telemetry.logger.core import (
    clear_log_output,
    configure_logging,
    get_logger,
    is_debug_enabled,
    is_trace_enabled,
    log_output_installed,
    logger,
    set_log_output,
)

__all__ = [
    "bind_context",
    "clear_context",
    "clear_log_output",
    "configure_logging",
    "get_context",
    "get_logger",
    "is_debug_enabled",
    "is_trace_enabled",
    "log_output_installed",
    "logger",
    "set_log_output",
    "unbind_context",
]
