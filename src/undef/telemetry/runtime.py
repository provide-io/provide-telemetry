# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Runtime config/policy update API."""

from __future__ import annotations

import threading

from undef.telemetry.backpressure import QueuePolicy, set_queue_policy
from undef.telemetry.config import TelemetryConfig
from undef.telemetry.resilience import ExporterPolicy, set_exporter_policy
from undef.telemetry.sampling import SamplingPolicy, set_sampling_policy

_lock = threading.Lock()
_active_config = TelemetryConfig.from_env({})


def apply_runtime_config(config: TelemetryConfig) -> None:
    global _active_config
    with _lock:
        _active_config = config
        set_sampling_policy("logs", SamplingPolicy(default_rate=config.sampling.logs_rate))
        set_sampling_policy("traces", SamplingPolicy(default_rate=config.sampling.traces_rate))
        set_sampling_policy("metrics", SamplingPolicy(default_rate=config.sampling.metrics_rate))
        set_queue_policy(
            QueuePolicy(
                logs_maxsize=config.backpressure.logs_maxsize,
                traces_maxsize=config.backpressure.traces_maxsize,
                metrics_maxsize=config.backpressure.metrics_maxsize,
            )
        )
        set_exporter_policy(
            "logs",
            ExporterPolicy(
                retries=config.exporter.logs_retries,
                backoff_seconds=config.exporter.logs_backoff_seconds,
                timeout_seconds=config.exporter.logs_timeout_seconds,
                fail_open=config.exporter.logs_fail_open,
                allow_blocking_in_event_loop=config.exporter.logs_allow_blocking_in_event_loop,
            ),
        )
        set_exporter_policy(
            "traces",
            ExporterPolicy(
                retries=config.exporter.traces_retries,
                backoff_seconds=config.exporter.traces_backoff_seconds,
                timeout_seconds=config.exporter.traces_timeout_seconds,
                fail_open=config.exporter.traces_fail_open,
                allow_blocking_in_event_loop=config.exporter.traces_allow_blocking_in_event_loop,
            ),
        )
        set_exporter_policy(
            "metrics",
            ExporterPolicy(
                retries=config.exporter.metrics_retries,
                backoff_seconds=config.exporter.metrics_backoff_seconds,
                timeout_seconds=config.exporter.metrics_timeout_seconds,
                fail_open=config.exporter.metrics_fail_open,
                allow_blocking_in_event_loop=config.exporter.metrics_allow_blocking_in_event_loop,
            ),
        )


def update_runtime_config(config: TelemetryConfig) -> TelemetryConfig:
    apply_runtime_config(config)
    return config


def reload_runtime_from_env() -> TelemetryConfig:
    cfg = TelemetryConfig.from_env()
    apply_runtime_config(cfg)
    return cfg


def get_runtime_config() -> TelemetryConfig:
    with _lock:
        if _active_config is None:
            return TelemetryConfig.from_env()
        return copy.deepcopy(_active_config)


def reset_runtime_for_tests() -> None:
    """Clear the cached runtime config snapshot."""
    global _active_config
    with _lock:
        _active_config = None
