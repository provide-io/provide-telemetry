# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Tests targeting surviving mutation-testing mutants in runtime.py.

Mutants primarily change signal name strings, config field mappings,
or replace ExporterPolicy with None in apply_runtime_config.
"""

from __future__ import annotations

import pytest

from undef.telemetry import backpressure as backpressure_mod
from undef.telemetry import health as health_mod
from undef.telemetry import resilience as resilience_mod
from undef.telemetry import runtime as runtime_mod
from undef.telemetry import sampling as sampling_mod
from undef.telemetry.config import (
    BackpressureConfig,
    ExporterPolicyConfig,
    SamplingConfig,
    TelemetryConfig,
)
from undef.telemetry.resilience import ExporterPolicy


@pytest.fixture(autouse=True)
def _reset() -> None:
    health_mod.reset_health_for_tests()
    sampling_mod.reset_sampling_for_tests()
    backpressure_mod.reset_queues_for_tests()
    resilience_mod.reset_resilience_for_tests()
    # Reset _active_config to None so lazy init is testable
    with runtime_mod._lock:
        runtime_mod._active_config = None


def test_apply_runtime_config_sampling_all_signals() -> None:
    """Kill mutants that swap signal names or config fields for sampling policies.

    Each signal gets a distinct non-default rate so any cross-wiring is detected.
    """
    cfg = TelemetryConfig(
        sampling=SamplingConfig(
            logs_rate=0.1,
            traces_rate=0.2,
            metrics_rate=0.3,
        ),
    )
    runtime_mod.apply_runtime_config(cfg)

    logs_policy = sampling_mod.get_sampling_policy("logs")
    traces_policy = sampling_mod.get_sampling_policy("traces")
    metrics_policy = sampling_mod.get_sampling_policy("metrics")

    assert logs_policy.default_rate == pytest.approx(0.1)
    assert traces_policy.default_rate == pytest.approx(0.2)
    assert metrics_policy.default_rate == pytest.approx(0.3)


def test_apply_runtime_config_backpressure_all_fields() -> None:
    """Kill mutants that swap backpressure field mappings."""
    cfg = TelemetryConfig(
        backpressure=BackpressureConfig(
            logs_maxsize=10,
            traces_maxsize=20,
            metrics_maxsize=30,
        ),
    )
    runtime_mod.apply_runtime_config(cfg)

    qp = backpressure_mod.get_queue_policy()
    assert qp.logs_maxsize == 10
    assert qp.traces_maxsize == 20
    assert qp.metrics_maxsize == 30


def test_apply_runtime_config_exporter_logs_all_fields() -> None:
    """Kill mutants in the logs ExporterPolicy construction.

    Every field gets a distinct non-default value so any dropped or swapped
    field is detected.
    """
    cfg = TelemetryConfig(
        exporter=ExporterPolicyConfig(
            logs_retries=3,
            logs_backoff_seconds=1.5,
            logs_timeout_seconds=20.0,
            logs_fail_open=False,
            logs_allow_blocking_in_event_loop=True,
        ),
    )
    runtime_mod.apply_runtime_config(cfg)

    p = resilience_mod.get_exporter_policy("logs")
    assert isinstance(p, ExporterPolicy)
    assert p.retries == 3
    assert p.backoff_seconds == pytest.approx(1.5)
    assert p.timeout_seconds == pytest.approx(20.0)
    assert p.fail_open is False
    assert p.allow_blocking_in_event_loop is True


def test_apply_runtime_config_exporter_traces_all_fields() -> None:
    """Kill mutants in the traces ExporterPolicy construction."""
    cfg = TelemetryConfig(
        exporter=ExporterPolicyConfig(
            traces_retries=4,
            traces_backoff_seconds=2.5,
            traces_timeout_seconds=25.0,
            traces_fail_open=False,
            traces_allow_blocking_in_event_loop=True,
        ),
    )
    runtime_mod.apply_runtime_config(cfg)

    p = resilience_mod.get_exporter_policy("traces")
    assert isinstance(p, ExporterPolicy)
    assert p.retries == 4
    assert p.backoff_seconds == pytest.approx(2.5)
    assert p.timeout_seconds == pytest.approx(25.0)
    assert p.fail_open is False
    assert p.allow_blocking_in_event_loop is True


def test_apply_runtime_config_exporter_metrics_all_fields() -> None:
    """Kill mutants in the metrics ExporterPolicy construction."""
    cfg = TelemetryConfig(
        exporter=ExporterPolicyConfig(
            metrics_retries=5,
            metrics_backoff_seconds=3.5,
            metrics_timeout_seconds=30.0,
            metrics_fail_open=False,
            metrics_allow_blocking_in_event_loop=True,
        ),
    )
    runtime_mod.apply_runtime_config(cfg)

    p = resilience_mod.get_exporter_policy("metrics")
    assert isinstance(p, ExporterPolicy)
    assert p.retries == 5
    assert p.backoff_seconds == pytest.approx(3.5)
    assert p.timeout_seconds == pytest.approx(30.0)
    assert p.fail_open is False
    assert p.allow_blocking_in_event_loop is True


def test_apply_runtime_config_exporter_signals_not_swapped() -> None:
    """Ensure logs/traces/metrics policies are assigned to the correct signals.

    Uses maximally distinct values per signal so any cross-wiring is detected.
    """
    cfg = TelemetryConfig(
        exporter=ExporterPolicyConfig(
            logs_retries=1,
            logs_backoff_seconds=0.1,
            logs_timeout_seconds=11.0,
            logs_fail_open=True,
            logs_allow_blocking_in_event_loop=False,
            traces_retries=2,
            traces_backoff_seconds=0.2,
            traces_timeout_seconds=22.0,
            traces_fail_open=False,
            traces_allow_blocking_in_event_loop=True,
            metrics_retries=3,
            metrics_backoff_seconds=0.3,
            metrics_timeout_seconds=33.0,
            metrics_fail_open=True,
            metrics_allow_blocking_in_event_loop=True,
        ),
    )
    runtime_mod.apply_runtime_config(cfg)

    logs = resilience_mod.get_exporter_policy("logs")
    traces = resilience_mod.get_exporter_policy("traces")
    metrics = resilience_mod.get_exporter_policy("metrics")

    # Logs
    assert logs.retries == 1
    assert logs.backoff_seconds == pytest.approx(0.1)
    assert logs.timeout_seconds == pytest.approx(11.0)
    assert logs.fail_open is True
    assert logs.allow_blocking_in_event_loop is False

    # Traces
    assert traces.retries == 2
    assert traces.backoff_seconds == pytest.approx(0.2)
    assert traces.timeout_seconds == pytest.approx(22.0)
    assert traces.fail_open is False
    assert traces.allow_blocking_in_event_loop is True

    # Metrics
    assert metrics.retries == 3
    assert metrics.backoff_seconds == pytest.approx(0.3)
    assert metrics.timeout_seconds == pytest.approx(33.0)
    assert metrics.fail_open is True
    assert metrics.allow_blocking_in_event_loop is True


def test_apply_runtime_config_deepcopies_config() -> None:
    """Ensure config is deepcopied so mutations to original don't affect runtime."""
    cfg = TelemetryConfig(
        sampling=SamplingConfig(logs_rate=0.5),
    )
    runtime_mod.apply_runtime_config(cfg)

    # Mutate the original
    cfg.sampling.logs_rate = 0.9

    # Runtime should still have 0.5
    active = runtime_mod.get_runtime_config()
    assert active.sampling.logs_rate == pytest.approx(0.5)


def test_get_runtime_config_lazy_init_from_env() -> None:
    """When no config has been applied, get_runtime_config returns TelemetryConfig.from_env()."""
    # _active_config is None (reset in fixture), so lazy init path is taken
    cfg = runtime_mod.get_runtime_config()
    assert isinstance(cfg, TelemetryConfig)


def test_apply_runtime_config_sampling_signals_not_swapped() -> None:
    """Ensure sampling rates go to the correct signal.

    Uses distinct values per signal to detect any cross-wiring.
    """
    cfg = TelemetryConfig(
        sampling=SamplingConfig(
            logs_rate=0.11,
            traces_rate=0.22,
            metrics_rate=0.33,
        ),
    )
    runtime_mod.apply_runtime_config(cfg)

    assert sampling_mod.get_sampling_policy("logs").default_rate == pytest.approx(0.11)
    assert sampling_mod.get_sampling_policy("traces").default_rate == pytest.approx(0.22)
    assert sampling_mod.get_sampling_policy("metrics").default_rate == pytest.approx(0.33)
