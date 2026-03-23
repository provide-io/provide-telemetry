# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Executor saturation load tests for resilience.py.

Tests three failure modes under sustained export failures:
- Ghost thread accumulation: circuit breaker bounds thread growth.
- Circuit breaker lifecycle: trip → block → half-open → reset → re-trip.
- Cross-signal isolation: a logs timeout storm cannot starve traces/metrics workers.
"""

from __future__ import annotations

import threading
import time
import types
from collections.abc import Callable, Iterator

import pytest

from undef.telemetry import health as health_mod
from undef.telemetry import resilience as resilience_mod
from undef.telemetry.resilience import ExporterPolicy, run_with_resilience

pytestmark = pytest.mark.integration

_TIMEOUT_S = 0.005  # 5 ms — tight enough to reliably time out a blocked op


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    resilience_mod.reset_resilience_for_tests()
    health_mod.reset_health_for_tests()
    yield
    # Tests must release their own events before this runs.
    # reset_resilience_for_tests() shuts down executors (wait=False) and clears
    # _timeout_executors so the next test gets a fresh pool.
    resilience_mod.reset_resilience_for_tests()
    health_mod.reset_health_for_tests()


def _make_stuck_op(event: threading.Event) -> Callable[[], str]:
    """Return an operation that blocks until *event* is set (5 s safety cap)."""

    def _op() -> str:
        event.wait(timeout=5.0)
        return "done"

    return _op


def _tight_policy(signal: str) -> None:
    """Set a tight-timeout, no-retry, fail-open policy for *signal*."""
    resilience_mod.set_exporter_policy(
        signal,
        ExporterPolicy(retries=0, timeout_seconds=_TIMEOUT_S, fail_open=True),
    )


def _trip_circuit(signal: str, event: threading.Event) -> None:
    """Submit exactly _CIRCUIT_BREAKER_THRESHOLD slow ops to trip the circuit."""
    threshold = resilience_mod._CIRCUIT_BREAKER_THRESHOLD
    for _ in range(threshold):
        result = run_with_resilience(signal, _make_stuck_op(event))
        assert result is None  # fail_open returns None on timeout
