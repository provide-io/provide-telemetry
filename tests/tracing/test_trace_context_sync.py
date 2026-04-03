# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for OTel trace context synchronization into contextvars."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from provide.telemetry.tracing import get_trace_context, set_trace_context, trace
from provide.telemetry.tracing import provider as provider_mod


def test_sync_otel_trace_context_with_real_span(monkeypatch: pytest.MonkeyPatch) -> None:
    """When OTel is available, _sync_otel_trace_context extracts IDs from the active span."""
    mock_ctx = SimpleNamespace(trace_id=0x1234567890ABCDEF1234567890ABCDEF, span_id=0x1234567890ABCDEF)
    mock_span = SimpleNamespace(get_span_context=lambda: mock_ctx)
    mock_api = SimpleNamespace(get_current_span=lambda: mock_span)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)
    monkeypatch.setattr(provider_mod, "_provider_configured", True)
    monkeypatch.setattr(provider_mod, "_load_otel_trace_api", lambda: mock_api)

    set_trace_context(None, None)
    provider_mod._sync_otel_trace_context()
    ctx = get_trace_context()
    assert ctx["trace_id"] == "1234567890abcdef1234567890abcdef"
    assert ctx["span_id"] == "1234567890abcdef"
    set_trace_context(None, None)


def test_sync_otel_trace_context_skips_invalid_span(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the span has zero trace/span IDs, context should not be updated."""
    mock_ctx = SimpleNamespace(trace_id=0, span_id=0)
    mock_span = SimpleNamespace(get_span_context=lambda: mock_ctx)
    mock_api = SimpleNamespace(get_current_span=lambda: mock_span)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)
    monkeypatch.setattr(provider_mod, "_provider_configured", True)
    monkeypatch.setattr(provider_mod, "_load_otel_trace_api", lambda: mock_api)

    set_trace_context("prev_trace", "prev_span")
    provider_mod._sync_otel_trace_context()
    ctx = get_trace_context()
    assert ctx["trace_id"] == "prev_trace"
    assert ctx["span_id"] == "prev_span"
    set_trace_context(None, None)


def test_sync_otel_trace_context_zero_trace_id_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """When trace_id is 0 but span_id is valid, context should not be updated."""
    mock_ctx = SimpleNamespace(trace_id=0, span_id=0xABCD)
    mock_span = SimpleNamespace(get_span_context=lambda: mock_ctx)
    mock_api = SimpleNamespace(get_current_span=lambda: mock_span)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)
    monkeypatch.setattr(provider_mod, "_provider_configured", True)
    monkeypatch.setattr(provider_mod, "_load_otel_trace_api", lambda: mock_api)

    set_trace_context("prev", "prev")
    provider_mod._sync_otel_trace_context()
    ctx = get_trace_context()
    assert ctx["trace_id"] == "prev"
    assert ctx["span_id"] == "prev"
    set_trace_context(None, None)


def test_sync_otel_trace_context_zero_span_id_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """When span_id is 0 but trace_id is valid, context should not be updated."""
    mock_ctx = SimpleNamespace(trace_id=0xABCD, span_id=0)
    mock_span = SimpleNamespace(get_span_context=lambda: mock_ctx)
    mock_api = SimpleNamespace(get_current_span=lambda: mock_span)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)
    monkeypatch.setattr(provider_mod, "_provider_configured", True)
    monkeypatch.setattr(provider_mod, "_load_otel_trace_api", lambda: mock_api)

    set_trace_context("prev", "prev")
    provider_mod._sync_otel_trace_context()
    ctx = get_trace_context()
    assert ctx["trace_id"] == "prev"
    assert ctx["span_id"] == "prev"
    set_trace_context(None, None)


def test_sync_otel_trace_context_no_otel(monkeypatch: pytest.MonkeyPatch) -> None:
    """When OTel is absent, _sync_otel_trace_context is a no-op."""
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", False)

    set_trace_context("existing", "ids")
    provider_mod._sync_otel_trace_context()
    ctx = get_trace_context()
    assert ctx["trace_id"] == "existing"
    assert ctx["span_id"] == "ids"
    set_trace_context(None, None)


def test_sync_otel_trace_context_unconfigured_provider_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulates: we installed a provider (otel_global_set=True) but it was shut down.
    monkeypatch.setattr(provider_mod, "_provider_configured", False)
    monkeypatch.setattr(provider_mod, "_otel_global_set", True)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)
    monkeypatch.setattr(provider_mod, "_load_otel_trace_api", lambda: SimpleNamespace())

    set_trace_context("existing", "ids")
    provider_mod._sync_otel_trace_context()
    assert get_trace_context() == {"trace_id": "existing", "span_id": "ids"}
    set_trace_context(None, None)


def test_sync_otel_trace_context_configured_but_api_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_mod, "_provider_configured", True)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)
    monkeypatch.setattr(provider_mod, "_load_otel_trace_api", lambda: None)

    set_trace_context("existing", "ids")
    provider_mod._sync_otel_trace_context()
    assert get_trace_context() == {"trace_id": "existing", "span_id": "ids"}
    set_trace_context(None, None)


def test_get_tracer_configured_but_api_missing_returns_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_mod, "_provider_configured", True)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)
    monkeypatch.setattr(provider_mod, "_load_otel_trace_api", lambda: None)

    tracer = provider_mod.get_tracer("x")
    assert isinstance(tracer, provider_mod._NoopTracer)


def test_sync_otel_trace_context_null_span_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """When get_span_context() returns None, context should not be updated."""
    mock_span = SimpleNamespace(get_span_context=lambda: None)
    mock_api = SimpleNamespace(get_current_span=lambda: mock_span)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)
    monkeypatch.setattr(provider_mod, "_provider_configured", True)
    monkeypatch.setattr(provider_mod, "_load_otel_trace_api", lambda: mock_api)

    set_trace_context("old_t", "old_s")
    provider_mod._sync_otel_trace_context()
    ctx = get_trace_context()
    assert ctx["trace_id"] == "old_t"
    assert ctx["span_id"] == "old_s"
    set_trace_context(None, None)


def test_trace_decorator_syncs_otel_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """The @trace decorator should sync OTel span IDs into get_trace_context()."""
    mock_ctx = SimpleNamespace(trace_id=0xABCDEF1234567890ABCDEF1234567890, span_id=0xFEDCBA0987654321)
    mock_span = SimpleNamespace(get_span_context=lambda: mock_ctx)

    class _OtelSpan:
        def __enter__(self) -> _OtelSpan:
            return self

        def __exit__(self, _a: object, _b: object, _c: object) -> None:
            pass

    class _OtelTracer:
        def start_as_current_span(self, _name: str, **_: object) -> _OtelSpan:
            return _OtelSpan()

    mock_api = SimpleNamespace(get_current_span=lambda: mock_span, get_tracer=lambda _n: _OtelTracer())
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)
    monkeypatch.setattr(provider_mod, "_provider_configured", True)
    monkeypatch.setattr(provider_mod, "_load_otel_trace_api", lambda: mock_api)
    monkeypatch.setattr("provide.telemetry.tracing.decorators.get_tracer", lambda _name: _OtelTracer())
    monkeypatch.setattr("provide.telemetry.sampling.should_sample", lambda _s, _n: True)
    monkeypatch.setattr("provide.telemetry.backpressure.try_acquire", lambda _s: object())
    monkeypatch.setattr("provide.telemetry.backpressure.release", lambda _t: None)

    captured: dict[str, str | None] = {}

    @trace("sync.otel.test")
    def fn() -> None:
        captured.update(get_trace_context())

    fn()
    assert captured["trace_id"] == "abcdef1234567890abcdef1234567890"
    assert captured["span_id"] == "fedcba0987654321"
    # After exit, context should be restored
    assert get_trace_context() == {"trace_id": None, "span_id": None}


# ── Mutation-killing tests for provider internals ──────────────────────


class TestResetTracingForTestsMutants:
    """Kill mutants in _reset_tracing_for_tests (_otel_global_set = False → None/True)."""

    def test_resets_otel_global_set_to_false(self) -> None:
        from provide.telemetry.tracing.provider import _reset_tracing_for_tests

        provider_mod._otel_global_set = True
        _reset_tracing_for_tests()
        assert provider_mod._otel_global_set is False

    def test_resets_baseline_captured_to_false(self) -> None:
        from provide.telemetry.tracing.provider import _reset_tracing_for_tests

        provider_mod._baseline_captured = True
        provider_mod._baseline_tracer_provider = object()
        _reset_tracing_for_tests()
        assert provider_mod._baseline_captured is False
        assert provider_mod._baseline_tracer_provider is None


class TestHasRealTracerProviderMutants:
    """Kill mutants in _has_real_tracer_provider (provider=None, is→is not)."""

    def test_identity_comparison_detects_real_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sentinel = object()
        fake_api = SimpleNamespace(get_tracer_provider=lambda: sentinel)
        monkeypatch.setattr(provider_mod, "_provider_configured", False)
        monkeypatch.setattr(provider_mod, "_otel_global_set", False)
        monkeypatch.setattr(provider_mod, "_baseline_captured", True)
        monkeypatch.setattr(provider_mod, "_baseline_tracer_provider", None)
        assert provider_mod._has_real_tracer_provider(fake_api) is True

    def test_same_default_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sentinel = object()
        fake_api = SimpleNamespace(get_tracer_provider=lambda: sentinel)
        monkeypatch.setattr(provider_mod, "_provider_configured", False)
        monkeypatch.setattr(provider_mod, "_otel_global_set", False)
        monkeypatch.setattr(provider_mod, "_baseline_captured", True)
        monkeypatch.setattr(provider_mod, "_baseline_tracer_provider", sentinel)
        assert provider_mod._has_real_tracer_provider(fake_api) is False

    def test_proxy_provider_before_baseline_captured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class ProxyTracerProvider:
            pass

        fake_api = SimpleNamespace(get_tracer_provider=lambda: ProxyTracerProvider())
        monkeypatch.setattr(provider_mod, "_provider_configured", False)
        monkeypatch.setattr(provider_mod, "_otel_global_set", False)
        monkeypatch.setattr(provider_mod, "_baseline_captured", False)
        assert provider_mod._has_real_tracer_provider(fake_api) is False

    def test_real_provider_before_baseline_captured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class RealTracerProvider:
            pass

        fake_api = SimpleNamespace(get_tracer_provider=lambda: RealTracerProvider())
        monkeypatch.setattr(provider_mod, "_provider_configured", False)
        monkeypatch.setattr(provider_mod, "_otel_global_set", False)
        monkeypatch.setattr(provider_mod, "_baseline_captured", False)
        assert provider_mod._has_real_tracer_provider(fake_api) is True


class TestGetTracerProviderPassthrough:
    """Kill get_tracer mutant that replaces otel_trace with None in provider check."""

    def test_get_tracer_passes_api_object_to_provider_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from provide.telemetry.tracing.provider import _NoopTracer, _reset_tracing_for_tests

        sentinel = object()

        class FakeTracer:
            def start_as_current_span(self, name: str, **kw: object) -> object:
                return SimpleNamespace(__enter__=lambda s: s, __exit__=lambda *_: None)

        fake_api = SimpleNamespace(
            get_tracer_provider=lambda: sentinel,
            get_tracer=lambda _name: FakeTracer(),
        )
        _reset_tracing_for_tests()
        monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)
        monkeypatch.setattr(provider_mod, "_baseline_captured", True)
        monkeypatch.setattr(provider_mod, "_baseline_tracer_provider", None)
        monkeypatch.setattr(provider_mod, "_load_otel_trace_api", lambda: fake_api)
        tracer = provider_mod.get_tracer()
        assert not isinstance(tracer, _NoopTracer)


class TestSyncOtelTraceContextProviderPassthrough:
    """Kill _sync_otel_trace_context mutant that passes None instead of otel_trace."""

    def test_sync_passes_api_object_to_provider_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sentinel = object()
        calls: list[object] = []
        mock_ctx = SimpleNamespace(trace_id=0xABCD, span_id=0xEF01)
        mock_span = SimpleNamespace(get_span_context=lambda: mock_ctx)

        def fake_get_tracer_provider() -> object:
            calls.append("get_tracer_provider")
            return sentinel

        fake_api = SimpleNamespace(
            get_tracer_provider=fake_get_tracer_provider,
            get_current_span=lambda: mock_span,
        )
        monkeypatch.setattr(provider_mod, "_provider_configured", False)
        monkeypatch.setattr(provider_mod, "_otel_global_set", False)
        monkeypatch.setattr(provider_mod, "_baseline_captured", True)
        monkeypatch.setattr(provider_mod, "_baseline_tracer_provider", None)
        monkeypatch.setattr(provider_mod, "_load_otel_trace_api", lambda: fake_api)
        provider_mod._sync_otel_trace_context()
        assert "get_tracer_provider" in calls
        set_trace_context(None, None)


class TestNoopSpanInitMutants:
    """Kill _NoopSpan.__init__ mutants (_prev_trace_id/span_id = None → '')."""

    def test_prev_ids_initialized_to_none(self) -> None:
        from provide.telemetry.tracing.provider import _NoopSpan

        span = _NoopSpan("test")
        assert span._prev_trace_id is None
        assert span._prev_span_id is None


class TestSetupTracingSetsGlobalFlag:
    """Kill setup_tracing mutmut_48/49: _otel_global_set = True → None/False."""

    def test_otel_global_set_is_true_after_setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from types import SimpleNamespace
        from unittest.mock import Mock

        from provide.telemetry.config import TelemetryConfig
        from provide.telemetry.tracing.provider import _reset_tracing_for_tests, setup_tracing

        _reset_tracing_for_tests()
        monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)

        fake_provider = SimpleNamespace(
            add_span_processor=Mock(),
            shutdown=Mock(),
        )
        provider_cls = Mock(return_value=fake_provider)
        resource_cls = SimpleNamespace(create=Mock(return_value="res"))
        processor_cls = Mock()
        exporter_cls = Mock()
        fake_otel = SimpleNamespace(
            set_tracer_provider=Mock(),
            get_tracer_provider=lambda: None,
            get_tracer=Mock(),
        )
        monkeypatch.setattr(
            provider_mod,
            "_load_otel_tracing_components",
            lambda: (resource_cls, provider_cls, processor_cls, exporter_cls),
        )
        monkeypatch.setattr(provider_mod, "_load_otel_trace_api", lambda: fake_otel)

        setup_tracing(TelemetryConfig())
        assert provider_mod._otel_global_set is True
