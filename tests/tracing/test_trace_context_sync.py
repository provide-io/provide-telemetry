# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Tests for OTel trace context synchronization into contextvars."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from undef.telemetry.tracing import get_trace_context, set_trace_context, trace
from undef.telemetry.tracing import provider as provider_mod


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


def test_sync_otel_trace_context_null_span_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """When get_span_context() returns None, context should not be updated."""
    mock_span = SimpleNamespace(get_span_context=lambda: None)
    mock_api = SimpleNamespace(get_current_span=lambda: mock_span)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)
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
    monkeypatch.setattr("undef.telemetry.tracing.decorators.get_tracer", lambda _name: _OtelTracer())
    monkeypatch.setattr("undef.telemetry.tracing.decorators.should_sample", lambda _s, _n: True)
    monkeypatch.setattr("undef.telemetry.tracing.decorators.try_acquire", lambda _s: object())
    monkeypatch.setattr("undef.telemetry.tracing.decorators.release", lambda _t: None)

    captured: dict[str, str | None] = {}

    @trace("sync.otel.test")
    def fn() -> None:
        captured.update(get_trace_context())

    fn()
    assert captured["trace_id"] == "abcdef1234567890abcdef1234567890"
    assert captured["span_id"] == "fedcba0987654321"
    # After exit, context should be restored
    assert get_trace_context() == {"trace_id": None, "span_id": None}
