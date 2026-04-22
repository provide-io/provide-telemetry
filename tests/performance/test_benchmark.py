# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""In-process performance smoke tests for hot-path telemetry operations.

These are NOT benchmarks with hard thresholds — they verify that hot-path
operations complete within a generous budget and detect catastrophic
regressions (e.g. accidental O(n^2) loops or lock contention).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from statistics import median

import pytest

from provide.telemetry.backpressure import reset_queues_for_tests
from provide.telemetry.health import reset_health_for_tests
from provide.telemetry.logger.processors import sanitize_sensitive_fields
from provide.telemetry.pii import reset_pii_rules_for_tests
from provide.telemetry.sampling import SamplingPolicy, reset_sampling_for_tests, set_sampling_policy, should_sample
from provide.telemetry.schema.events import event_name, validate_event_name

pytestmark = pytest.mark.integration

ITERATIONS = 50_000
# Budget: operations must complete within this many ns/op on average.
# These are very generous — 10x slower than typical to avoid flakes.
MAX_EVENT_NAME_NS = 25_000
MAX_SHOULD_SAMPLE_NS = 25_000
MAX_SANITIZE_NS = 25_000
MAX_VALIDATE_NS = 25_000


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    reset_sampling_for_tests()
    reset_queues_for_tests()
    reset_health_for_tests()
    reset_pii_rules_for_tests()


_CallableT = Callable[[], object]


def _ns_per_op(fn: _CallableT, iterations: int = ITERATIONS) -> float:
    """Run fn in a tight loop and return average nanoseconds per call."""
    start = time.perf_counter_ns()
    for _ in range(iterations):
        fn()
    elapsed = time.perf_counter_ns() - start
    return elapsed / iterations


def _stable_ns_per_op(
    fn: _CallableT,
    iterations: int = ITERATIONS,
    repeats: int = 5,
) -> float:
    """Return a median ns/op sample to damp scheduler jitter in CI."""
    fn()
    samples = [_ns_per_op(fn, iterations) for _ in range(max(1, repeats))]
    return float(median(samples))


class TestEventNamePerformance:
    def test_three_segment_event_name(self) -> None:
        ns = _stable_ns_per_op(lambda: event_name("auth", "login", "success"))
        assert ns < MAX_EVENT_NAME_NS, f"event_name(3 seg) too slow: {ns:.0f} ns/op"

    def test_five_segment_event_name(self) -> None:
        ns = _stable_ns_per_op(lambda: event_name("payment", "subscription", "renewal", "charge", "success"))
        assert ns < MAX_EVENT_NAME_NS, f"event_name(5 seg) too slow: {ns:.0f} ns/op"

    def test_validate_event_name_strict(self) -> None:
        ns = _stable_ns_per_op(lambda: validate_event_name("auth.login.success", strict_event_name=True))
        assert ns < MAX_VALIDATE_NS, f"validate_event_name too slow: {ns:.0f} ns/op"


class TestSamplingPerformance:
    def test_should_sample_rate_one(self) -> None:
        set_sampling_policy("logs", SamplingPolicy(default_rate=1.0))
        ns = _stable_ns_per_op(lambda: should_sample("logs"))
        assert ns < MAX_SHOULD_SAMPLE_NS, f"should_sample(rate=1) too slow: {ns:.0f} ns/op"

    def test_should_sample_rate_zero(self) -> None:
        set_sampling_policy("logs", SamplingPolicy(default_rate=0.0))
        ns = _stable_ns_per_op(lambda: should_sample("logs"))
        assert ns < MAX_SHOULD_SAMPLE_NS, f"should_sample(rate=0) too slow: {ns:.0f} ns/op"

    def test_should_sample_with_key_override(self) -> None:
        set_sampling_policy("logs", SamplingPolicy(default_rate=0.5, overrides={"auth.login": 1.0}))
        ns = _stable_ns_per_op(lambda: should_sample("logs", key="auth.login"))
        assert ns < MAX_SHOULD_SAMPLE_NS, f"should_sample(override) too slow: {ns:.0f} ns/op"


class TestSanitizePerformance:
    def test_sanitize_small_payload(self) -> None:
        processor = sanitize_sensitive_fields(enabled=True)
        payload = {"password": "secret", "token": "abc", "request_id": "r1"}  # pragma: allowlist secret
        ns = _stable_ns_per_op(lambda: processor(None, "info", payload))
        assert ns < MAX_SANITIZE_NS, f"sanitize(small) too slow: {ns:.0f} ns/op"

    def test_sanitize_large_payload(self) -> None:
        processor = sanitize_sensitive_fields(enabled=True)
        payload = {f"field_{i}": f"value_{i}" for i in range(50)}
        payload["password"] = "secret"  # pragma: allowlist secret
        ns = _stable_ns_per_op(lambda: processor(None, "info", payload), iterations=10_000, repeats=3)
        assert ns < MAX_SANITIZE_NS * 20, f"sanitize(large) too slow: {ns:.0f} ns/op"

    def test_sanitize_disabled_is_fast(self) -> None:
        processor = sanitize_sensitive_fields(enabled=False)
        payload = {"password": "secret", "token": "abc"}  # pragma: allowlist secret
        ns = _stable_ns_per_op(lambda: processor(None, "info", payload))
        assert ns < MAX_SANITIZE_NS, f"sanitize(disabled) too slow: {ns:.0f} ns/op"
