# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Telemetry setup coordinator."""

from __future__ import annotations

import threading

from undef.telemetry.config import TelemetryConfig
from undef.telemetry.logger.core import _reset_logging_for_tests as _reset_logging
from undef.telemetry.logger.core import configure_logging, shutdown_logging
from undef.telemetry.metrics.provider import _set_meter_for_test as _reset_metrics
from undef.telemetry.metrics.provider import setup_metrics, shutdown_metrics
from undef.telemetry.runtime import apply_runtime_config
from undef.telemetry.slo import record_red_metrics, record_use_metrics
from undef.telemetry.tracing.provider import _reset_tracing_for_tests as _reset_tracing
from undef.telemetry.tracing.provider import setup_tracing, shutdown_tracing

_lock = threading.Lock()
_setup_done = False


def setup_telemetry(config: TelemetryConfig | None = None) -> TelemetryConfig:
    global _setup_done
    cfg = config or TelemetryConfig.from_env()
    with _lock:
        if not _setup_done:
            apply_runtime_config(cfg)
            configure_logging(cfg)
            setup_tracing(cfg)
            setup_metrics(cfg)
            if cfg.slo.enable_red_metrics:
                record_red_metrics("startup", "INIT", 200, 0.0)
            if cfg.slo.enable_use_metrics:
                record_use_metrics("startup", 0)
            _setup_done = True
    return cfg


def _reset_setup_state_for_tests() -> None:
    global _setup_done
    _setup_done = False


def _reset_all_for_tests() -> None:
    global _setup_done
    _setup_done = False
    _reset_logging()
    _reset_tracing()
    _reset_metrics(None)


def shutdown_telemetry() -> None:
    """Flush and tear down telemetry providers when available."""
    global _setup_done
    with _lock:
        _setup_done = False
        shutdown_logging()
        shutdown_metrics()
        shutdown_tracing()
