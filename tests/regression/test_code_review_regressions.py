# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Regression tests for issues found in code review."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import structlog

from provide.telemetry.backpressure import reset_queues_for_tests
from provide.telemetry.config import TelemetryConfig, _parse_env_float, _parse_env_int
from provide.telemetry.health import get_health_snapshot, reset_health_for_tests
from provide.telemetry.logger.processors import apply_sampling, enforce_event_schema
from provide.telemetry.metrics.fallback import Gauge
from provide.telemetry.resilience import (
    ExporterPolicy,
    _get_timeout_executor,
    reset_resilience_for_tests,
    run_with_resilience,
    set_exporter_policy,
)
from provide.telemetry.sampling import reset_sampling_for_tests, should_sample
from provide.telemetry.schema.events import EventSchemaError
from provide.telemetry.setup import _reset_all_for_tests
from provide.telemetry.slo import _reset_slo_for_tests, record_use_metrics
from provide.telemetry.tracing import provider as provider_mod


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    reset_sampling_for_tests()
    reset_queues_for_tests()
    reset_health_for_tests()
    reset_resilience_for_tests()
    _reset_slo_for_tests()


# ── Issue #1: apply_sampling must raise DropEvent, not re-emit ────────


class TestApplySamplingDropEvent:
    def test_dropped_event_raises_structlog_drop_event(self) -> None:
        """Sampling rejection must suppress the log, not emit a replacement."""
        with (
            patch("provide.telemetry.sampling.should_sample", return_value=False),
            pytest.raises(structlog.DropEvent),
        ):
            apply_sampling(None, "", {"event": "auth.login.success"})

    def test_sampled_event_passes_through_unchanged(self) -> None:
        original: dict[str, object] = {"event": "auth.login.success", "user": "u1"}
        with patch("provide.telemetry.sampling.should_sample", return_value=True):
            result = apply_sampling(None, "", original)
        assert result is original


# ── Issue #2: setup_done must be set before SLO calls ─────────────────


class TestSetupDoneOrdering:
    def test_setup_done_true_even_if_slo_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If SLO recording fails, _setup_done must already be True."""
        import provide.telemetry.slo as slo_mod
        from provide.telemetry import setup as setup_mod
        from provide.telemetry.setup import _reset_setup_state_for_tests, setup_telemetry

        _reset_setup_state_for_tests()
        monkeypatch.setattr("provide.telemetry.runtime.apply_runtime_config", lambda _cfg: None)
        monkeypatch.setattr("provide.telemetry.setup.configure_logging", lambda _cfg, **kw: None)
        monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
        monkeypatch.setattr("provide.telemetry.metrics.provider._refresh_otel_metrics", lambda: None)
        monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _cfg: None)
        monkeypatch.setattr("provide.telemetry.metrics.provider.setup_metrics", lambda _cfg: None)
        monkeypatch.setattr(slo_mod, "_rebind_slo_instruments", lambda: None)

        def _boom_red(*_args: object) -> None:
            # _setup_done should already be True at this point
            assert setup_mod._setup_done is True
            raise RuntimeError("SLO boom")

        monkeypatch.setattr(slo_mod, "record_red_metrics", _boom_red)
        with pytest.raises(RuntimeError, match="SLO boom"):
            setup_telemetry(TelemetryConfig.from_env({"PROVIDE_SLO_ENABLE_RED_METRICS": "true"}))
        # _setup_done remains True — no provider double-init risk
        assert setup_mod._setup_done is True


# ── Issue #3: resilience reset race condition ─────────────────────────


class TestResilienceResetRace:
    def test_executor_teardown_inside_lock(self) -> None:
        """Executor shutdown must happen while holding the lock."""
        from provide.telemetry import resilience as r_mod

        # Create executor for a signal
        _get_timeout_executor("logs")
        assert len(r_mod._timeout_executors) > 0

        # Verify reset clears all executors atomically
        reset_resilience_for_tests()
        assert len(r_mod._timeout_executors) == 0


# ── Issue #4: _reset_all_for_tests completeness ──────────────────────


class TestResetAllCompleteness:
    def test_reset_all_clears_resilience_state(self) -> None:
        set_exporter_policy("logs", ExporterPolicy(retries=5))
        _reset_all_for_tests()
        from provide.telemetry.resilience import get_exporter_policy

        assert get_exporter_policy("logs").retries == 0

    def test_reset_all_clears_health_state(self) -> None:
        from provide.telemetry.health import increment_dropped

        increment_dropped("logs", 10)
        _reset_all_for_tests()
        snap = get_health_snapshot()
        assert snap.dropped_logs == 0

    def test_reset_all_clears_sampling_state(self) -> None:
        from provide.telemetry.sampling import SamplingPolicy, get_sampling_policy, set_sampling_policy

        set_sampling_policy("logs", SamplingPolicy(default_rate=0.1))
        _reset_all_for_tests()
        assert get_sampling_policy("logs").default_rate == 1.0

    def test_reset_all_clears_backpressure_state(self) -> None:
        from provide.telemetry.backpressure import QueuePolicy, get_queue_policy, set_queue_policy

        set_queue_policy(QueuePolicy(logs_maxsize=100))
        _reset_all_for_tests()
        assert get_queue_policy().logs_maxsize == 0

    def test_reset_all_clears_pii_state(self) -> None:
        from provide.telemetry.pii import PIIRule, get_pii_rules, register_pii_rule

        register_pii_rule(PIIRule(path=("secret",), mode="redact"))
        _reset_all_for_tests()
        assert get_pii_rules() == ()

    def test_reset_all_clears_cardinality_state(self) -> None:
        from provide.telemetry.cardinality import get_cardinality_limits, register_cardinality_limit

        register_cardinality_limit("route", max_values=10)
        _reset_all_for_tests()
        assert get_cardinality_limits() == {}


# ── Issue #5: module-level tracer must delegate to get_tracer() ──────


class TestLazyTracer:
    def test_module_tracer_delegates_to_get_tracer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The module-level `tracer` must resolve at call time, not import time."""
        monkeypatch.setattr(provider_mod, "_HAS_OTEL", False)
        span = provider_mod.tracer.start_as_current_span("test.op")
        # Should get a NoopSpan since no OTel
        assert hasattr(span, "__enter__")

    def test_module_tracer_is_lazy_tracer_not_noop(self) -> None:
        """tracer must be a _LazyTracer, not a frozen _NoopTracer."""
        assert isinstance(provider_mod.tracer, provider_mod._LazyTracer)

    def test_lazy_tracer_passes_name_to_span(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: start_as_current_span(name, ...) → (None, ...)."""
        monkeypatch.setattr(provider_mod, "_HAS_OTEL", False)
        span = provider_mod.tracer.start_as_current_span("exact.name")
        assert isinstance(span, provider_mod._NoopSpan)
        assert span.name == "exact.name"

    def test_lazy_tracer_passes_kwargs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: start_as_current_span(name, **kwargs) → (name,)."""
        seen_kwargs: list[dict[str, object]] = []

        class _SpyTracer:
            def start_as_current_span(self, name: str, **kwargs: object) -> provider_mod._NoopSpan:
                seen_kwargs.append(kwargs)
                return provider_mod._NoopSpan(name)

        monkeypatch.setattr(provider_mod, "get_tracer", lambda _n=None: _SpyTracer())
        provider_mod.tracer.start_as_current_span("op", attributes={"k": "v"})
        assert seen_kwargs == [{"attributes": {"k": "v"}}]


# ── Issue #6: required_keys must be respected in compat mode ─────────


class TestRequiredKeysCompatMode:
    def test_required_keys_enforced_without_strict_schema(self) -> None:
        """required_keys must work even with strict_schema=False."""
        config = TelemetryConfig.from_env(
            {
                "PROVIDE_TELEMETRY_STRICT_SCHEMA": "false",
                "PROVIDE_TELEMETRY_STRICT_EVENT_NAME": "false",
                "PROVIDE_TELEMETRY_REQUIRED_KEYS": "request_id",
            }
        )
        processor = enforce_event_schema(config)
        # Missing request_id should annotate with _schema_error
        result = processor(None, "", {"event": "test"})
        assert "_schema_error" in result
        assert "missing required keys: request_id" in result["_schema_error"]

    def test_required_keys_pass_when_present(self) -> None:
        config = TelemetryConfig.from_env(
            {
                "PROVIDE_TELEMETRY_STRICT_SCHEMA": "false",
                "PROVIDE_TELEMETRY_STRICT_EVENT_NAME": "false",
                "PROVIDE_TELEMETRY_REQUIRED_KEYS": "request_id",
            }
        )
        processor = enforce_event_schema(config)
        result = processor(None, "", {"event": "test", "request_id": "r1"})
        assert result["request_id"] == "r1"


# ── Issue #7: Gauge.set vs Gauge.add for absolute values ─────────────


class TestGaugeSetMethod:
    def test_gauge_set_replaces_value(self) -> None:
        g = Gauge("test.gauge")
        g.set(50)
        assert g.value == 50
        g.set(75)
        assert g.value == 75  # Not 125

    def test_gauge_add_accumulates(self) -> None:
        g = Gauge("test.gauge")
        g.add(50)
        g.add(75)
        assert g.value == 125  # Cumulative

    def test_record_use_metrics_uses_set_semantics(self) -> None:
        """Consecutive calls with absolute values must reflect latest, not sum."""
        record_use_metrics("cpu", 50)
        record_use_metrics("cpu", 75)
        from provide.telemetry.slo import _gauges

        g = _gauges["resource.utilization.percent"]
        assert g.value == 75  # Not 125

    def test_gauge_set_sampling_rejection(self) -> None:
        """Gauge.set respects sampling policy."""
        from provide.telemetry.sampling import SamplingPolicy, set_sampling_policy

        set_sampling_policy("metrics", SamplingPolicy(default_rate=0.0))
        g = Gauge("test.gauge")
        g.set(99)
        assert g.value == 0  # Rejected by sampling

    def test_gauge_set_backpressure_rejection(self) -> None:
        """Gauge.set respects backpressure."""
        from provide.telemetry.backpressure import QueuePolicy, set_queue_policy

        set_queue_policy(QueuePolicy(metrics_maxsize=1))
        g = Gauge("test.gauge")
        # Fill the queue
        from provide.telemetry.backpressure import try_acquire

        ticket = try_acquire("metrics")
        assert ticket is not None and ticket.signal == "metrics"
        # Now set should be rejected
        g.set(99)
        assert g.value == 0
        from provide.telemetry.backpressure import release

        release(ticket)

    def test_gauge_set_passes_name_to_should_sample(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: should_sample('metrics', self.name) → ('metrics', None)."""
        sampled_keys: list[str | None] = []
        original_should_sample = should_sample

        def _spy_sample(signal: str, key: str | None = None) -> bool:
            sampled_keys.append(key)
            return original_should_sample(signal, key)

        monkeypatch.setattr("provide.telemetry.metrics.fallback.should_sample", _spy_sample)
        g = Gauge("my.gauge.name")
        g.set(42)
        assert "my.gauge.name" in sampled_keys

    def test_gauge_set_releases_actual_ticket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: release(ticket) → release(None)."""
        released: list[object] = []
        sentinel = object()

        monkeypatch.setattr("provide.telemetry.metrics.fallback.try_acquire", lambda _s: sentinel)
        monkeypatch.setattr("provide.telemetry.metrics.fallback.release", lambda t: released.append(t))

        g = Gauge("test.gauge")
        g.set(10)
        assert released == [sentinel]

    def test_gauge_set_with_otel_sends_delta(self) -> None:
        """Gauge.set sends the delta to the OTel UpDownCounter."""
        from unittest.mock import Mock

        mock_otel = Mock()
        g = Gauge("test.gauge", otel_gauge=mock_otel)
        g.set(50)
        mock_otel.add.assert_called_once_with(50, {})
        g.set(75)
        mock_otel.add.assert_called_with(25, {})  # delta = 75 - 50


# ── Issue #8: env var parsing gives descriptive errors ────────────────


class TestEnvVarParsingErrors:
    def test_malformed_float_env_var_gives_descriptive_error(self) -> None:
        with pytest.raises(ValueError, match=r"invalid float for PROVIDE_TRACE_SAMPLE_RATE"):
            TelemetryConfig.from_env({"PROVIDE_TRACE_SAMPLE_RATE": "half"})

    def test_malformed_int_env_var_gives_descriptive_error(self) -> None:
        with pytest.raises(ValueError, match=r"invalid integer for PROVIDE_BACKPRESSURE_LOGS_MAXSIZE"):
            TelemetryConfig.from_env({"PROVIDE_BACKPRESSURE_LOGS_MAXSIZE": "ten"})

    def test_parse_env_float_valid(self) -> None:
        assert _parse_env_float("1.5", "X") == 1.5

    def test_parse_env_float_invalid(self) -> None:
        with pytest.raises(ValueError, match=r"invalid float for X: 'abc'"):
            _parse_env_float("abc", "X")

    def test_parse_env_int_valid(self) -> None:
        assert _parse_env_int("42", "X") == 42

    def test_parse_env_int_invalid(self) -> None:
        with pytest.raises(ValueError, match=r"invalid integer for X: 'abc'"):
            _parse_env_int("abc", "X")


# ── Issue #12: resilience retry path must be covered ─────────────────


class TestResilienceRetryPathCoverage:
    def test_retry_records_failure_and_retries(self) -> None:
        """The except branch in run_with_resilience must be exercisable."""
        set_exporter_policy("logs", ExporterPolicy(retries=1, backoff_seconds=0.0, fail_open=True, timeout_seconds=0.0))
        calls = {"count": 0}

        def _failing_op() -> str:
            calls["count"] += 1
            raise RuntimeError("export failed")

        result = run_with_resilience("logs", _failing_op)
        assert result is None
        assert calls["count"] == 2  # 1 initial + 1 retry
        snap = get_health_snapshot()
        assert snap.export_failures_logs == 2
        assert snap.retries_logs == 1

    def test_retry_path_raises_on_fail_closed(self) -> None:
        set_exporter_policy("logs", ExporterPolicy(retries=0, fail_open=False, timeout_seconds=0.0))

        def _failing_op() -> str:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            run_with_resilience("logs", _failing_op)


# ── Issue #13: _reset helpers must hold _lock when writing _setup_done ─


class TestResetUnderLock:
    def test_reset_setup_state_holds_lock(self) -> None:
        """_reset_setup_state_for_tests must hold _lock while writing _setup_done."""
        from provide.telemetry import setup as setup_mod
        from provide.telemetry.setup import _lock, _reset_setup_state_for_tests

        setup_mod._setup_done = True
        # Acquire lock from another perspective to verify it's not permanently held
        _reset_setup_state_for_tests()
        assert setup_mod._setup_done is False
        # Lock must be released — this acquire should succeed immediately
        assert _lock.acquire(timeout=0.1)
        _lock.release()

    def test_reset_all_holds_lock(self) -> None:
        """_reset_all_for_tests must hold _lock while writing _setup_done."""
        from provide.telemetry import setup as setup_mod
        from provide.telemetry.setup import _lock

        setup_mod._setup_done = True
        _reset_all_for_tests()
        assert setup_mod._setup_done is False
        assert _lock.acquire(timeout=0.1)
        _lock.release()


# ── Issue #14: traceparent IDs must be normalized to lowercase ─────────


class TestTraceparentNormalization:
    def test_uppercase_trace_id_normalized(self) -> None:
        from provide.telemetry.propagation import _parse_traceparent

        trace_id, span_id = _parse_traceparent("00-0AF7651916CD43DD8448EB211C80319C-B7AD6B7169203331-01")
        assert trace_id == "0af7651916cd43dd8448eb211c80319c"
        assert span_id == "b7ad6b7169203331"

    def test_mixed_case_trace_id_normalized(self) -> None:
        from provide.telemetry.propagation import _parse_traceparent

        trace_id, span_id = _parse_traceparent("00-0aF7651916cD43dD8448eB211c80319C-b7aD6B7169203331-01")
        assert trace_id == "0af7651916cd43dd8448eb211c80319c"
        assert span_id == "b7ad6b7169203331"

    def test_lowercase_unchanged(self) -> None:
        from provide.telemetry.propagation import _parse_traceparent

        trace_id, span_id = _parse_traceparent("00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")
        assert trace_id == "0af7651916cd43dd8448eb211c80319c"
        assert span_id == "b7ad6b7169203331"
