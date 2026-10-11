# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""A runtime update that fails partway leaves the previous policies in force.

``apply_policies`` writes the sampling, queue and exporter policies one at a
time, before the logging pipeline is rebuilt and the generation is published.
When either of those later steps raised, the new policies stayed applied under
the old generation: a config nobody could read back was steering every signal.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from provide.telemetry import backpressure as backpressure_mod
from provide.telemetry import resilience as resilience_mod
from provide.telemetry import runtime as runtime_mod
from provide.telemetry import sampling as sampling_mod
from provide.telemetry._lifecycle import coordinator
from provide.telemetry._runtime_policies import rolled_back_on_failure
from provide.telemetry.config import (
    BackpressureConfig,
    ExporterPolicyConfig,
    LoggingConfig,
    RuntimeOverrides,
    SamplingConfig,
    TelemetryConfig,
)
from provide.telemetry.logger import core as logger_core
from provide.telemetry.resilience import ExporterPolicy
from provide.telemetry.sampling import SamplingPolicy

_SIGNALS = ("logs", "traces", "metrics")


@pytest.fixture(autouse=True)
def _reset() -> None:
    sampling_mod.reset_sampling_for_tests()
    backpressure_mod.reset_queues_for_tests()
    resilience_mod.reset_resilience_for_tests()
    runtime_mod.reset_runtime_for_tests()


def _policies() -> tuple[Any, ...]:
    return (
        tuple(sampling_mod.get_sampling_policy(signal) for signal in _SIGNALS),
        backpressure_mod.get_queue_policy(),
        tuple(resilience_mod.get_exporter_policy(signal) for signal in _SIGNALS),
    )


def _new_policies() -> RuntimeOverrides:
    return RuntimeOverrides(
        sampling=SamplingConfig(logs_rate=0.25, traces_rate=0.5, metrics_rate=0.75),
        backpressure=BackpressureConfig(logs_maxsize=3, traces_maxsize=4, metrics_maxsize=5),
        exporter=ExporterPolicyConfig(logs_retries=2, traces_retries=3, metrics_retries=4),
        logging=LoggingConfig(level="DEBUG"),
    )


def _fail(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError("step failed")


def test_a_failed_logging_rebuild_restores_every_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_mod.apply_runtime_config(TelemetryConfig())
    before = _policies()
    published = coordinator.peek().config
    monkeypatch.setattr(logger_core, "configure_logging", _fail)

    with pytest.raises(RuntimeError, match="step failed"):
        runtime_mod.update_runtime_config(_new_policies())

    assert _policies() == before
    assert coordinator.peek().config == published


def test_a_failed_publication_restores_every_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_mod.apply_runtime_config(TelemetryConfig())
    before = _policies()
    # The coordinator's slots make publish read-only; swap the whole object.
    stand_in = SimpleNamespace(operations=coordinator.operations, peek=coordinator.peek, publish=_fail)
    monkeypatch.setattr(runtime_mod, "coordinator", stand_in)

    with pytest.raises(RuntimeError, match="step failed"):
        runtime_mod.update_runtime_config(RuntimeOverrides(sampling=SamplingConfig(logs_rate=0.25)))
    assert _policies() == before

    with pytest.raises(RuntimeError, match="step failed"):
        runtime_mod.apply_runtime_config(TelemetryConfig(sampling=SamplingConfig(logs_rate=0.25)))
    assert _policies() == before


def test_a_policy_install_that_fails_partway_restores_the_ones_already_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sampling and queue policies are written before the exporter step raises."""
    from provide.telemetry import _runtime_policies

    runtime_mod.apply_runtime_config(TelemetryConfig())
    before = _policies()
    real = resilience_mod.set_exporter_policy
    calls: list[str] = []

    def _fail_first(signal: Any, policy: ExporterPolicy) -> None:
        calls.append(signal)
        if len(calls) == 1:
            raise RuntimeError("step failed")
        real(signal, policy)

    monkeypatch.setattr(_runtime_policies, "set_exporter_policy", _fail_first)

    with pytest.raises(RuntimeError, match="step failed"):
        runtime_mod.update_runtime_config(_new_policies())

    monkeypatch.undo()
    assert _policies() == before
    # The first write raised; the rollback then restored all three signals.
    assert calls == ["logs", "logs", "traces", "metrics"]


def test_a_successful_update_keeps_the_new_policies(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_mod.apply_runtime_config(TelemetryConfig())
    monkeypatch.setattr(logger_core, "configure_logging", lambda *_a, **_k: None)

    runtime_mod.update_runtime_config(_new_policies())

    sampling, queue, exporter = _policies()
    assert [policy.default_rate for policy in sampling] == [0.25, 0.5, 0.75]
    assert (queue.logs_maxsize, queue.traces_maxsize, queue.metrics_maxsize) == (3, 4, 5)
    assert [policy.retries for policy in exporter] == [2, 3, 4]


def test_the_rollback_restores_policies_set_outside_any_config() -> None:
    """What is restored is what was in force, not what the old config said."""
    sampling_mod.set_sampling_policy("logs", SamplingPolicy(default_rate=0.5, overrides={"noisy.event": 0.0}))
    resilience_mod.set_exporter_policy("traces", ExporterPolicy(retries=1))
    before = _policies()

    with pytest.raises(RuntimeError, match="inside"), rolled_back_on_failure():
        sampling_mod.set_sampling_policy("logs", SamplingPolicy(default_rate=1.0))
        resilience_mod.set_exporter_policy("traces", ExporterPolicy(retries=5))
        backpressure_mod.set_queue_policy(backpressure_mod.QueuePolicy(logs_maxsize=9))
        raise RuntimeError("inside")

    assert _policies() == before
    assert sampling_mod.get_sampling_policy("logs").overrides == {"noisy.event": 0.0}


def test_the_rollback_leaves_policies_alone_when_nothing_fails() -> None:
    with rolled_back_on_failure():
        sampling_mod.set_sampling_policy("metrics", SamplingPolicy(default_rate=0.1))
    assert sampling_mod.get_sampling_policy("metrics").default_rate == 0.1
