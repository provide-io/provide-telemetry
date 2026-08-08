# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Pushing a config generation's hot policy values into the signal subsystems.

Split from ``runtime.py`` to keep that module under the 500-line ceiling. This
is the "apply" half of a lifecycle publication: the runtime module decides
*which* config becomes the next generation, and this decides what the signal
subsystems have to be told about it.
"""

from __future__ import annotations

__all__ = ["apply_policies"]

from provide.telemetry.backpressure import QueuePolicy, set_queue_policy
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.resilience import ExporterPolicy, set_exporter_policy
from provide.telemetry.sampling import SamplingPolicy, set_sampling_policy


def apply_policies(snapshot: TelemetryConfig) -> None:
    """Push hot policy values from a config snapshot to signal subsystems. Lock-free."""
    set_sampling_policy(
        "logs", SamplingPolicy(default_rate=snapshot.sampling.logs_rate)
    )  # pragma: no mutate — signal name string is the API contract; pinned across reloads
    set_sampling_policy(
        "traces",
        SamplingPolicy(default_rate=min(snapshot.sampling.traces_rate, snapshot.tracing.sample_rate)),
    )
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
