# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Runtime config/policy update API."""

from __future__ import annotations

import copy
import threading

from undef.telemetry.backpressure import QueuePolicy, set_queue_policy
from undef.telemetry.config import TelemetryConfig
from undef.telemetry.resilience import ExporterPolicy, set_exporter_policy
from undef.telemetry.sampling import SamplingPolicy, set_sampling_policy

_lock = threading.Lock()
_active_config = TelemetryConfig.from_env({})


def apply_runtime_config(config: TelemetryConfig) -> None:
    """Apply a config snapshot to runtime signal policies."""
    global _active_config
    with _lock:
        snapshot = copy.deepcopy(config)
        _active_config = snapshot
        set_sampling_policy("logs", SamplingPolicy(default_rate=snapshot.sampling.logs_rate))
        set_sampling_policy("traces", SamplingPolicy(default_rate=snapshot.sampling.traces_rate))
        set_sampling_policy("metrics", SamplingPolicy(default_rate=snapshot.sampling.metrics_rate))
        set_queue_policy(
            QueuePolicy(
                logs_maxsize=snapshot.backpressure.logs_maxsize,
                traces_maxsize=snapshot.backpressure.traces_maxsize,
                metrics_maxsize=snapshot.backpressure.metrics_maxsize,
            )
        )
        set_exporter_policy(
            "logs",
            ExporterPolicy(
                retries=snapshot.exporter.logs_retries,
                backoff_seconds=snapshot.exporter.logs_backoff_seconds,
                timeout_seconds=snapshot.exporter.logs_timeout_seconds,
                fail_open=snapshot.exporter.logs_fail_open,
                allow_blocking_in_event_loop=snapshot.exporter.logs_allow_blocking_in_event_loop,
            ),
        )
        set_exporter_policy(
            "traces",
            ExporterPolicy(
                retries=snapshot.exporter.traces_retries,
                backoff_seconds=snapshot.exporter.traces_backoff_seconds,
                timeout_seconds=snapshot.exporter.traces_timeout_seconds,
                fail_open=snapshot.exporter.traces_fail_open,
                allow_blocking_in_event_loop=snapshot.exporter.traces_allow_blocking_in_event_loop,
            ),
        )
        set_exporter_policy(
            "metrics",
            ExporterPolicy(
                retries=snapshot.exporter.metrics_retries,
                backoff_seconds=snapshot.exporter.metrics_backoff_seconds,
                timeout_seconds=snapshot.exporter.metrics_timeout_seconds,
                fail_open=snapshot.exporter.metrics_fail_open,
                allow_blocking_in_event_loop=snapshot.exporter.metrics_allow_blocking_in_event_loop,
            ),
        )


def update_runtime_config(config: TelemetryConfig) -> TelemetryConfig:
    """Apply config and return the active runtime snapshot."""
    apply_runtime_config(config)
    return get_runtime_config()


def reload_runtime_from_env() -> TelemetryConfig:
    """Reload environment config, apply it, and return the active snapshot."""
    cfg = TelemetryConfig.from_env()
    apply_runtime_config(cfg)
    return get_runtime_config()


def get_runtime_config() -> TelemetryConfig:
    """Return a defensive copy of the active runtime config snapshot."""
    with _lock:
        return copy.deepcopy(_active_config)
