# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Telemetry setup coordinator."""

from __future__ import annotations

import threading

from undef.telemetry.config import TelemetryConfig
from undef.telemetry.logger.core import configure_logging, shutdown_logging
from undef.telemetry.metrics.provider import setup_metrics, shutdown_metrics
from undef.telemetry.tracing.provider import setup_tracing, shutdown_tracing

_lock = threading.Lock()
_setup_done = False


def setup_telemetry(config: TelemetryConfig | None = None) -> TelemetryConfig:
    global _setup_done
    cfg = config or TelemetryConfig.from_env()
    with _lock:
        if not _setup_done:
            configure_logging(cfg)
            setup_tracing(cfg)
            setup_metrics(cfg)
            _setup_done = True
    return cfg


def _reset_setup_state_for_tests() -> None:
    global _setup_done
    _setup_done = False


def shutdown_telemetry() -> None:
    """Flush and tear down telemetry providers when available."""
    shutdown_logging()
    shutdown_metrics()
    shutdown_tracing()
