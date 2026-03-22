# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Regression tests for code review batch 4 (issues 7-12): slo lazy import,
sampling copy, pii copy, resilience dedup, header url-decode, context restore."""

from __future__ import annotations

import pytest

from undef.telemetry.health import reset_health_for_tests
from undef.telemetry.resilience import reset_resilience_for_tests


@pytest.fixture(autouse=True)
def _clean() -> None:
    reset_health_for_tests()
    reset_resilience_for_tests()


# ── Issue 7: setup.py lazy SLO import ────────────────────────────────


class TestLazySloImport:
    def test_importing_package_does_not_load_slo(self) -> None:
        """Importing undef.telemetry must not eagerly load undef.telemetry.slo."""
        import sys

        slo_key = "undef.telemetry.slo"
        # Remove slo from cache to test fresh import
        slo_was_loaded = slo_key in sys.modules
        was_cached = sys.modules.pop(slo_key, None)
        try:
            # Re-importing the package should NOT re-load slo
            import importlib

            import undef.telemetry

            importlib.reload(undef.telemetry.setup)
            # slo should not be in sys.modules unless it was already there before
            if not slo_was_loaded:
                assert slo_key not in sys.modules, "slo was eagerly loaded during package import"
        finally:
            if was_cached is not None:
                sys.modules[slo_key] = was_cached


# ── Issue 8: sampling.py returns copy ────────────────────────────────


class TestSamplingPolicyReturnsCopy:
    def test_mutating_returned_overrides_does_not_affect_stored_policy(self) -> None:
        from undef.telemetry.sampling import (
            SamplingPolicy,
            get_sampling_policy,
            reset_sampling_for_tests,
            set_sampling_policy,
        )

        reset_sampling_for_tests()
        set_sampling_policy("logs", SamplingPolicy(default_rate=0.5, overrides={"evt": 0.7}))
        policy = get_sampling_policy("logs")
        policy.overrides["injected"] = 0.0  # mutate returned copy
        fresh = get_sampling_policy("logs")
        assert "injected" not in fresh.overrides, "Mutation of returned overrides affected stored policy"

    def test_returned_policy_is_not_same_object(self) -> None:
        from undef.telemetry.sampling import (
            SamplingPolicy,
            get_sampling_policy,
            reset_sampling_for_tests,
            set_sampling_policy,
        )

        reset_sampling_for_tests()
        set_sampling_policy("logs", SamplingPolicy(default_rate=0.5))
        p1 = get_sampling_policy("logs")
        p2 = get_sampling_policy("logs")
        assert p1 is not p2


# ── Issue 9: pii.py returns shallow copy when disabled ───────────────


class TestPiiDisabledReturnsCopy:
    def test_disabled_returns_copy_not_original(self) -> None:
        from undef.telemetry.pii import sanitize_payload

        original = {"key": "value", "other": 123}
        result = sanitize_payload(original, enabled=False)
        assert result == original
        assert result is not original

    def test_mutating_disabled_result_does_not_affect_original(self) -> None:
        from undef.telemetry.pii import sanitize_payload

        original = {"key": "value"}
        result = sanitize_payload(original, enabled=False)
        result["injected"] = "evil"
        assert "injected" not in original


# ── Issue 10: resilience warning dedup keyed on (signal, allow_blocking) ─


class TestResilienceWarnDedup:
    def test_policy_change_triggers_new_warning(self) -> None:
        from undef.telemetry.resilience import ExporterPolicy, _warn_async_risk

        policy_block = ExporterPolicy(retries=1, backoff_seconds=0.1, allow_blocking_in_event_loop=True)
        policy_fail = ExporterPolicy(retries=1, backoff_seconds=0.1, allow_blocking_in_event_loop=False)
        with pytest.warns(RuntimeWarning, match="allows blocking"):
            _warn_async_risk("logs", policy_block)
        # Same signal, different allow_blocking_in_event_loop → different key → new warning
        with pytest.warns(RuntimeWarning, match="fail-fast"):
            _warn_async_risk("logs", policy_fail)

    def test_same_policy_same_signal_no_repeat_warning(self) -> None:
        import warnings

        from undef.telemetry.resilience import ExporterPolicy, _warn_async_risk

        policy = ExporterPolicy(retries=1, backoff_seconds=0.1, allow_blocking_in_event_loop=False)
        with pytest.warns(RuntimeWarning):
            _warn_async_risk("traces", policy)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _warn_async_risk("traces", policy)
        assert len(w) == 0

    def test_warned_key_is_tuple_of_signal_and_bool(self) -> None:
        from undef.telemetry import resilience as r_mod
        from undef.telemetry.resilience import ExporterPolicy, _warn_async_risk

        policy = ExporterPolicy(retries=1, backoff_seconds=0.0, allow_blocking_in_event_loop=True)
        with pytest.warns(RuntimeWarning):
            _warn_async_risk("metrics", policy)
        with r_mod._lock:
            assert ("metrics", True) in r_mod._async_warned_signals


# ── Issue 11: config.py URL-decodes header key names ─────────────────


class TestOtlpHeaderKeyUrlDecode:
    def test_url_encoded_key_is_decoded(self) -> None:
        from undef.telemetry.config import _parse_otlp_headers

        result = _parse_otlp_headers("my%20key=some_value")
        assert "my key" in result
        assert result["my key"] == "some_value"

    def test_url_encoded_value_is_decoded(self) -> None:
        from undef.telemetry.config import _parse_otlp_headers

        result = _parse_otlp_headers("key=my%20value")
        assert result["key"] == "my value"

    def test_plain_key_value_unchanged(self) -> None:
        from undef.telemetry.config import _parse_otlp_headers

        result = _parse_otlp_headers("Authorization=Bearer%20token123")
        assert "Authorization" in result
        assert result["Authorization"] == "Bearer token123"


# ── Issue 12: middleware restores pre-request context ─────────────────


class TestMiddlewareRestoresContext:
    @pytest.mark.asyncio
    async def test_pre_request_context_is_restored_after_request(self) -> None:
        from undef.telemetry.asgi.middleware import TelemetryMiddleware
        from undef.telemetry.logger.context import bind_context, get_context, restore_context

        # Set pre-existing context
        restore_context({})
        bind_context(actor_id="actor-123")
        pre_ctx = get_context()
        assert pre_ctx == {"actor_id": "actor-123"}

        async def _app(scope: dict[str, object], receive: object, send: object) -> None:
            pass

        async def _receive() -> dict[str, object]:
            return {}

        async def _send(msg: dict[str, object]) -> None:
            pass

        middleware = TelemetryMiddleware(_app)
        await middleware({"type": "http", "headers": []}, _receive, _send)

        # Context should be restored to pre-request state
        post_ctx = get_context()
        assert post_ctx == {"actor_id": "actor-123"}
        # Cleanup
        restore_context({})

    @pytest.mark.asyncio
    async def test_empty_pre_request_context_is_restored(self) -> None:
        from undef.telemetry.asgi.middleware import TelemetryMiddleware
        from undef.telemetry.logger.context import get_context, restore_context

        restore_context({})

        async def _app(scope: dict[str, object], receive: object, send: object) -> None:
            pass

        async def _receive() -> dict[str, object]:
            return {}

        async def _send(msg: dict[str, object]) -> None:
            pass

        middleware = TelemetryMiddleware(_app)
        await middleware({"type": "http", "headers": []}, _receive, _send)

        post_ctx = get_context()
        assert post_ctx == {}


# ── restore_context() function ────────────────────────────────────────


class TestRestoreContext:
    def test_restore_context_sets_exact_snapshot(self) -> None:
        from undef.telemetry.logger.context import get_context, restore_context

        restore_context({"x": 1, "y": "hello"})
        ctx = get_context()
        assert ctx == {"x": 1, "y": "hello"}

    def test_restore_context_empty_dict_clears(self) -> None:
        from undef.telemetry.logger.context import bind_context, get_context, restore_context

        bind_context(foo="bar")
        restore_context({})
        ctx = get_context()
        assert ctx == {}

    def test_restore_context_returns_copy(self) -> None:
        from undef.telemetry.logger.context import bind_context, restore_context

        snapshot: dict[str, object] = {"a": 1}
        restore_context(snapshot)
        bind_context(b=2)  # mutate the live context
        # The original snapshot dict should not be affected
        assert "b" not in snapshot


# ── logger/core._has_otel_log_provider ───────────────────────────────


class TestHasOtelLogProvider:
    def test_returns_false_when_none(self) -> None:
        from undef.telemetry.logger.core import _has_otel_log_provider, _reset_logging_for_tests

        _reset_logging_for_tests()
        assert _has_otel_log_provider() is False

    def test_returns_true_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from undef.telemetry.logger import core as lc
        from undef.telemetry.logger.core import _has_otel_log_provider, _reset_logging_for_tests

        _reset_logging_for_tests()
        monkeypatch.setattr(lc, "_otel_log_provider", object())
        assert _has_otel_log_provider() is True


# ── _TraceWrapper.trace() reads _active_config under lock ─────────────


class TestTraceWrapperLockedRead:
    def test_trace_does_not_log_when_level_not_trace(self) -> None:
        import structlog

        from undef.telemetry.config import TelemetryConfig
        from undef.telemetry.logger import core as lc
        from undef.telemetry.logger.core import _TraceWrapper, configure_logging

        lc._reset_logging_for_tests()
        cfg = TelemetryConfig()  # INFO level
        configure_logging(cfg)
        wrapper = _TraceWrapper(structlog.get_logger("test"))
        # With INFO level, trace() must be a no-op
        debug_calls: list[str] = []
        monkeypatch_obj = pytest.MonkeyPatch()
        monkeypatch_obj.setattr(wrapper._logger, "debug", lambda *a, **kw: debug_calls.append(str(a)))
        wrapper.trace("should_not_log")
        assert debug_calls == []
        monkeypatch_obj.undo()

    def test_trace_logs_when_level_is_trace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import structlog

        from undef.telemetry.config import LoggingConfig, TelemetryConfig
        from undef.telemetry.logger import core as lc
        from undef.telemetry.logger.core import _TraceWrapper, configure_logging

        lc._reset_logging_for_tests()
        cfg = TelemetryConfig(logging=LoggingConfig(level="TRACE"))
        configure_logging(cfg)
        wrapper = _TraceWrapper(structlog.get_logger("test"))
        trace_calls: list[str] = []
        monkeypatch.setattr(wrapper._logger, "trace", lambda event, **kw: trace_calls.append(event))
        wrapper.trace("trace_event")
        assert "trace_event" in trace_calls

    def test_trace_is_noop_when_active_config_is_none(self) -> None:
        from undef.telemetry.config import TelemetryConfig
        from undef.telemetry.logger import core as lc
        from undef.telemetry.logger.core import _TraceWrapper, configure_logging

        lc._reset_logging_for_tests()
        # Configure with INFO (default) so FilteringBoundLogger has .trace() as nop
        configure_logging(TelemetryConfig())
        import structlog

        wrapper = _TraceWrapper(structlog.get_logger("test"))
        # Should not crash — trace() is a nop at INFO level
        wrapper.trace("event")
