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

__all__ = ["apply_policies", "rolled_back_on_failure"]

from collections.abc import Generator
from contextlib import contextmanager

from provide.telemetry.backpressure import QueuePolicy, get_queue_policy, set_queue_policy
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.resilience import ExporterPolicy, get_exporter_policy, set_exporter_policy
from provide.telemetry.sampling import SamplingPolicy, get_sampling_policy, set_sampling_policy

_SIGNALS = ("logs", "traces", "metrics")


@contextmanager
def rolled_back_on_failure() -> Generator[None]:
    """Put back every policy ``apply_policies`` writes if the block raises.

    ``apply_policies`` installs the policies one at a time, and the update that
    calls it still has the logging rebuild and the publication ahead of it.
    When either of those raised, the new policies stayed in force under the old
    generation -- steering every signal by a config nobody could read back.

    What is restored is what was in force on entry, read from the subsystems
    themselves rather than recomputed from the previous config: a policy a
    caller set directly is not one the config knows about.
    """
    sampling = [(signal, get_sampling_policy(signal)) for signal in _SIGNALS]
    queue = get_queue_policy()
    exporter = [(signal, get_exporter_policy(signal)) for signal in _SIGNALS]
    try:
        yield
    except BaseException:
        for signal, sampling_policy in sampling:
            set_sampling_policy(signal, sampling_policy)
        set_queue_policy(queue)
        for signal, exporter_policy in exporter:
            set_exporter_policy(signal, exporter_policy)
        raise


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
