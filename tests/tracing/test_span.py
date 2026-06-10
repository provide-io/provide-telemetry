# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Block-level span() context manager and its companions.

span() is the sync, attribute-aware block primitive that shares the @trace
governance lifecycle (consent -> sampling -> backpressure -> health -> OTel
context sync -> restore). These tests pin the attribute coercion, exception
recording, the no-op path, the log<->trace correlation that the decorator
provides, and the governance gates.
"""

from __future__ import annotations

from collections.abc import Generator
from types import SimpleNamespace
from typing import Any

import pytest

from provide.telemetry.consent import ConsentLevel, set_consent_level
from provide.telemetry.health import get_health_snapshot, reset_health_for_tests
from provide.telemetry.tracing import provider as provider_mod
from provide.telemetry.tracing.context import get_span_id, get_trace_context, get_trace_id, set_trace_context
from provide.telemetry.tracing.provider import _NoopSpan, _reset_tracing_for_tests
from provide.telemetry.tracing.span import _set_span_attr, record_exception, set_attrs, span

pytestmark = pytest.mark.otel


@pytest.fixture
def captured_spans(monkeypatch: pytest.MonkeyPatch) -> Generator[Any]:
    """Resolve get_tracer() to a live in-memory-backed SDK tracer (hermetic).

    Gates are forced open so a real span is always created; get_current_span is
    wired to the real OTel API so _sync_otel_trace_context() can read the span.
    """
    sdk_trace = pytest.importorskip("opentelemetry.sdk.trace")
    in_memory = pytest.importorskip("opentelemetry.sdk.trace.export.in_memory_span_exporter")
    export_module = pytest.importorskip("opentelemetry.sdk.trace.export")
    otel_trace_api = pytest.importorskip("opentelemetry.trace")

    provider = sdk_trace.TracerProvider()
    exporter = in_memory.InMemorySpanExporter()
    provider.add_span_processor(export_module.SimpleSpanProcessor(exporter))
    test_tracer = provider.get_tracer("test")
    fake_api = SimpleNamespace(
        get_tracer=lambda *_a, **_k: test_tracer,
        get_current_span=otel_trace_api.get_current_span,
    )
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)
    monkeypatch.setattr(provider_mod, "_provider_configured", True)
    monkeypatch.setattr(provider_mod, "_load_otel_trace_api", lambda: fake_api)
    monkeypatch.setattr("provide.telemetry.sampling.should_sample", lambda _s, _n: True)
    monkeypatch.setattr("provide.telemetry.backpressure.try_acquire", lambda _s: object())
    monkeypatch.setattr("provide.telemetry.backpressure.release", lambda _t: None)
    try:
        yield exporter
    finally:
        provider.shutdown()


def test_span_filters_and_coerces_attributes(captured_spans: Any) -> None:
    """None dropped; primitives/lists pass through; everything else stringified."""
    sentinel = object()

    with span(
        "op.run",
        primitive=7,
        skipped=None,
        primitive_list=[1, 2, 3],
        mixed_list=[1, sentinel],
        other=sentinel,
    ) as sp:
        assert sp is not None

    finished = captured_spans.get_finished_spans()
    assert len(finished) == 1
    recorded = finished[0]
    assert recorded.name == "op.run"
    attrs = dict(recorded.attributes)
    assert attrs["primitive"] == 7
    assert "skipped" not in attrs
    assert list(attrs["primitive_list"]) == [1, 2, 3]
    # A sequence with a non-primitive element is not a valid OTel sequence, so
    # the whole value is stringified rather than passed through and dropped.
    assert attrs["mixed_list"] == str([1, sentinel])
    assert attrs["other"] == str(sentinel)


def test_span_records_and_reraises_exception(captured_spans: Any) -> None:
    """A raising body propagates and the span is marked ERROR with the event."""
    status_code = pytest.importorskip("opentelemetry.trace.status").StatusCode

    with pytest.raises(ValueError, match="boom"), span("op.fails"):
        raise ValueError("boom")

    finished = captured_spans.get_finished_spans()
    assert len(finished) == 1
    recorded = finished[0]
    assert recorded.status.status_code == status_code.ERROR
    assert any(event.name == "exception" for event in recorded.events)


def test_span_syncs_trace_context_inside_and_restores_after(captured_spans: Any) -> None:
    """Inside the block the OTel span IDs are mirrored into our contextvars; after, restored."""
    set_trace_context("prev_t", "prev_s")
    with span("op.correlated") as sp:
        sctx = sp.get_span_context()
        assert get_trace_id() == format(sctx.trace_id, "032x")
        assert get_span_id() == format(sctx.span_id, "016x")
    assert get_trace_context() == {"trace_id": "prev_t", "span_id": "prev_s"}


def test_span_noop_when_tracing_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no real provider, span() yields a NoopSpan and never errors."""
    _reset_tracing_for_tests()
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", False)
    with span("op.noop", attr="set-on-noop") as sp:
        assert isinstance(sp, _NoopSpan)


def test_span_bypasses_span_when_not_sampled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not sampled -> body runs untraced, no span emitted, NoopSpan yielded."""
    reset_health_for_tests()
    monkeypatch.setattr("provide.telemetry.sampling.should_sample", lambda _s, _n: False)
    entered = []
    with span("op.unsampled") as sp:
        entered.append(True)
    assert entered == [True]
    assert isinstance(sp, _NoopSpan)
    assert get_health_snapshot().emitted_traces == 0


def test_span_bypasses_span_when_consent_denied() -> None:
    """consent=NONE -> body runs untraced, no span emitted."""
    reset_health_for_tests()
    set_consent_level(ConsentLevel.NONE)
    with span("op.noconsent") as sp:
        assert isinstance(sp, _NoopSpan)
    assert get_health_snapshot().emitted_traces == 0


def test_span_bypasses_span_under_backpressure(monkeypatch: pytest.MonkeyPatch) -> None:
    """No backpressure ticket -> body runs untraced, no span emitted."""
    reset_health_for_tests()
    monkeypatch.setattr("provide.telemetry.sampling.should_sample", lambda _s, _n: True)
    monkeypatch.setattr("provide.telemetry.backpressure.try_acquire", lambda _s: None)
    with span("op.full") as sp:
        assert isinstance(sp, _NoopSpan)
    assert get_health_snapshot().emitted_traces == 0


def test_span_releases_backpressure_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    """The acquired ticket is released when the span block exits."""
    _reset_tracing_for_tests()
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", False)
    releases: list[object] = []
    ticket = object()
    monkeypatch.setattr("provide.telemetry.sampling.should_sample", lambda _s, _n: True)
    monkeypatch.setattr("provide.telemetry.backpressure.try_acquire", lambda _s: ticket)
    monkeypatch.setattr("provide.telemetry.backpressure.release", lambda t: releases.append(t))
    with span("op.ticket"):
        pass
    assert releases == [ticket]


def test_set_attrs_sets_on_live_span_and_skips_none(captured_spans: Any) -> None:
    """set_attrs coerces and applies attributes to a live span, dropping None."""
    sentinel = object()
    with span("op.setattrs") as sp:
        set_attrs(sp, kept=5, dropped=None, coerced=sentinel)
    recorded = captured_spans.get_finished_spans()[0]
    attrs = dict(recorded.attributes)
    assert attrs["kept"] == 5
    assert "dropped" not in attrs
    assert attrs["coerced"] == str(sentinel)


def test_set_attrs_safe_on_noop() -> None:
    """set_attrs on a NoopSpan (no set_attribute) is a silent no-op."""
    set_attrs(_NoopSpan("x"), a=1, b=None)


def test_record_exception_marks_error_without_raising(captured_spans: Any) -> None:
    """record_exception marks the span ERROR and records the event, without raising."""
    status_code = pytest.importorskip("opentelemetry.trace.status").StatusCode
    with span("op.recexc") as sp:
        record_exception(sp, ValueError("noted"))
    recorded = captured_spans.get_finished_spans()[0]
    assert recorded.status.status_code == status_code.ERROR
    assert any(event.name == "exception" for event in recorded.events)


def test_record_exception_safe_on_noop() -> None:
    """record_exception on a NoopSpan is a silent no-op."""
    record_exception(_NoopSpan("x"), ValueError("ignored"))


def test_set_span_attr_swallows_setter_errors() -> None:
    """A span whose set_attribute raises must not blow up the caller."""

    class _BadSpan:
        def set_attribute(self, _key: str, _value: object) -> None:
            raise RuntimeError("cannot set")

    _set_span_attr(_BadSpan(), "k", 1)  # no raise
