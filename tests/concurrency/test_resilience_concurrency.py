# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Concurrency tests for resilience, PII, and cardinality subsystems.

Verifies thread safety of lock-protected state under real contention.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from provide.telemetry.cardinality import clear_cardinality_limits, get_cardinality_limits, register_cardinality_limit
from provide.telemetry.health import reset_health_for_tests
from provide.telemetry.pii import PIIRule, get_pii_rules, register_pii_rule, reset_pii_rules_for_tests, sanitize_payload
from provide.telemetry.resilience import (
    ExporterPolicy,
    get_exporter_policy,
    reset_resilience_for_tests,
    run_with_resilience,
    set_exporter_policy,
)

pytestmark = pytest.mark.integration

WORKERS = 8
ITERATIONS = 100


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    reset_resilience_for_tests()
    reset_pii_rules_for_tests()
    reset_health_for_tests()
    clear_cardinality_limits()


# ── Resilience: concurrent policy reads/writes ─────────────────────────


class TestResilienceConcurrency:
    def test_concurrent_set_get_policy_no_corruption(self) -> None:
        """Concurrent policy set/get must not crash or return invalid state."""
        barrier = threading.Barrier(WORKERS)
        errors: list[Exception] = []

        def _writer() -> None:
            barrier.wait(timeout=2.0)
            try:
                for i in range(ITERATIONS):
                    set_exporter_policy(
                        "logs",
                        ExporterPolicy(retries=i % 5, backoff_seconds=0.1 * (i % 10)),
                    )
            except Exception as exc:
                errors.append(exc)

        def _reader() -> None:
            barrier.wait(timeout=2.0)
            try:
                for _ in range(ITERATIONS):
                    policy = get_exporter_policy("logs")
                    assert policy.retries >= 0
                    assert policy.backoff_seconds >= 0.0
            except Exception as exc:
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [
                *[pool.submit(_writer) for _ in range(WORKERS // 2)],
                *[pool.submit(_reader) for _ in range(WORKERS // 2)],
            ]
            for f in as_completed(futures):
                f.result()

        assert errors == []

    def test_concurrent_run_with_resilience_fail_open(self) -> None:
        """Multiple threads calling run_with_resilience simultaneously."""
        set_exporter_policy(
            "logs",
            ExporterPolicy(retries=1, backoff_seconds=0.0, fail_open=True, timeout_seconds=0.0),
        )
        barrier = threading.Barrier(WORKERS)
        call_count = {"value": 0}
        lock = threading.Lock()

        def _failing_op() -> str:
            with lock:
                call_count["value"] += 1
            raise RuntimeError("concurrent fail")

        def _run() -> None:
            barrier.wait(timeout=2.0)
            for _ in range(10):
                run_with_resilience("logs", _failing_op)

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(_run) for _ in range(WORKERS)]
            for f in as_completed(futures):
                f.result()

        # Each worker does 10 iterations, each with 1 initial + 1 retry = 2 calls
        assert call_count["value"] == WORKERS * 10 * 2

    def test_concurrent_policy_updates_all_signals(self) -> None:
        """Updating policies for different signals concurrently is safe."""
        barrier = threading.Barrier(3)
        errors: list[Exception] = []

        def _set_signal(signal: str) -> None:
            barrier.wait(timeout=2.0)
            try:
                for i in range(ITERATIONS):
                    set_exporter_policy(signal, ExporterPolicy(retries=i % 3))
            except Exception as exc:
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [
                pool.submit(_set_signal, "logs"),
                pool.submit(_set_signal, "traces"),
                pool.submit(_set_signal, "metrics"),
            ]
            for f in as_completed(futures):
                f.result()

        assert errors == []


# ── PII: concurrent rule registration and sanitization ─────────────────


class TestPIIConcurrency:
    def test_concurrent_register_and_get_rules(self) -> None:
        """Concurrent rule registration must not lose or corrupt rules."""
        barrier = threading.Barrier(WORKERS)

        def _register(thread_id: int) -> None:
            barrier.wait(timeout=2.0)
            for i in range(20):
                register_pii_rule(PIIRule(path=(f"t{thread_id}_f{i}",), mode="redact"))

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(_register, tid) for tid in range(WORKERS)]
            for f in as_completed(futures):
                f.result()

        rules = get_pii_rules()
        assert len(rules) == WORKERS * 20

    def test_concurrent_sanitize_does_not_crash(self) -> None:
        """Sanitizing payloads concurrently must not crash."""
        register_pii_rule(PIIRule(path=("secret",), mode="redact"))
        barrier = threading.Barrier(WORKERS)
        errors: list[Exception] = []

        def _sanitize() -> None:
            barrier.wait(timeout=2.0)
            try:
                for i in range(ITERATIONS):
                    payload = {"secret": f"val-{i}", "safe": f"data-{i}"}
                    result = sanitize_payload(payload, enabled=True)
                    assert result["secret"] == "***"
                    assert result["safe"] == f"data-{i}"
            except Exception as exc:
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(_sanitize) for _ in range(WORKERS)]
            for f in as_completed(futures):
                f.result()

        assert errors == []


# ── Cardinality: concurrent limit registration ─────────────────────────


class TestCardinalityConcurrency:
    def test_concurrent_register_limits(self) -> None:
        """Concurrent cardinality limit registration must not corrupt state."""
        barrier = threading.Barrier(WORKERS)

        def _register(thread_id: int) -> None:
            barrier.wait(timeout=2.0)
            for i in range(20):
                register_cardinality_limit(f"t{thread_id}_dim{i}", max_values=100 + i)

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(_register, tid) for tid in range(WORKERS)]
            for f in as_completed(futures):
                f.result()

        limits = get_cardinality_limits()
        assert len(limits) == WORKERS * 20

    def test_concurrent_register_and_clear(self) -> None:
        """Registration and clearing concurrently must not crash."""
        barrier = threading.Barrier(4)
        errors: list[Exception] = []

        def _register() -> None:
            barrier.wait(timeout=2.0)
            try:
                for i in range(ITERATIONS):
                    register_cardinality_limit(f"dim_{i}", max_values=10)
            except Exception as exc:
                errors.append(exc)

        def _clear() -> None:
            barrier.wait(timeout=2.0)
            try:
                for _ in range(ITERATIONS):
                    clear_cardinality_limits()
            except Exception as exc:
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(_register),
                pool.submit(_register),
                pool.submit(_clear),
                pool.submit(_clear),
            ]
            for f in as_completed(futures):
                f.result()

        assert errors == []
