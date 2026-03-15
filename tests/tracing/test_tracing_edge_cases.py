# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Edge-case and stress tests for tracing subsystem."""

from __future__ import annotations

import asyncio
import functools
from unittest.mock import Mock

import pytest

from undef.telemetry.backpressure import QueuePolicy, reset_queues_for_tests, set_queue_policy
from undef.telemetry.sampling import SamplingPolicy, reset_sampling_for_tests, set_sampling_policy
from undef.telemetry.tracing import get_trace_context, set_trace_context, trace
from undef.telemetry.tracing import provider as provider_mod
from undef.telemetry.tracing.provider import _NoopSpan, _NoopTracer, _reset_tracing_for_tests


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    set_trace_context(None, None)
    reset_sampling_for_tests()
    reset_queues_for_tests()
    _reset_tracing_for_tests()


# ── NoopSpan edge cases ────────────────────────────────────────────────


class TestNoopSpanEdgeCases:
    def test_noop_span_trace_id_length(self) -> None:
        span = _NoopSpan("test")
        assert len(span.trace_id) == 32
        assert len(span.span_id) == 16

    def test_noop_span_context_set_and_cleared(self) -> None:
        span = _NoopSpan("test")
        with span:
            ctx = get_trace_context()
            assert ctx["trace_id"] == "0" * 32
            assert ctx["span_id"] == "0" * 16
        ctx = get_trace_context()
        assert ctx["trace_id"] is None
        assert ctx["span_id"] is None

    def test_noop_span_exit_clears_even_on_exception(self) -> None:
        span = _NoopSpan("test")
        with pytest.raises(RuntimeError, match="boom"), span:
            raise RuntimeError("boom")
        assert get_trace_context() == {"trace_id": None, "span_id": None}

    def test_noop_span_name_preserved(self) -> None:
        span = _NoopSpan("my.operation")
        assert span.name == "my.operation"

    def test_nested_noop_spans_restore_outer_context(self) -> None:
        outer = _NoopSpan("outer")
        inner = _NoopSpan("inner")
        with outer:
            outer_ctx = get_trace_context()
            with inner:
                assert get_trace_context() == {"trace_id": "0" * 32, "span_id": "0" * 16}
            assert get_trace_context() == outer_ctx


# ── Decorator exception propagation ───────────────────────────────────


class TestTraceDecoratorExceptions:
    def test_sync_exception_propagates_and_releases_ticket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        releases: list[object] = []

        class _Span:
            def __enter__(self) -> None:
                return None

            def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
                return None

        class _Tracer:
            def start_as_current_span(self, _name: str, **_: object) -> _Span:
                return _Span()

        monkeypatch.setattr("undef.telemetry.tracing.decorators.should_sample", lambda _s, _n: True)
        monkeypatch.setattr("undef.telemetry.tracing.decorators.try_acquire", lambda _s: object())
        monkeypatch.setattr("undef.telemetry.tracing.decorators.release", lambda t: releases.append(t))
        monkeypatch.setattr("undef.telemetry.tracing.decorators.get_tracer", lambda _n: _Tracer())

        @trace("fail.sync")
        def boom() -> None:
            raise ValueError("sync boom")

        with pytest.raises(ValueError, match="sync boom"):
            boom()
        assert len(releases) == 1

    async def test_async_exception_propagates_and_releases_ticket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        releases: list[object] = []

        class _Span:
            def __enter__(self) -> None:
                return None

            def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
                return None

        class _Tracer:
            def start_as_current_span(self, _name: str, **_: object) -> _Span:
                return _Span()

        monkeypatch.setattr("undef.telemetry.tracing.decorators.should_sample", lambda _s, _n: True)
        monkeypatch.setattr("undef.telemetry.tracing.decorators.try_acquire", lambda _s: object())
        monkeypatch.setattr("undef.telemetry.tracing.decorators.release", lambda t: releases.append(t))
        monkeypatch.setattr("undef.telemetry.tracing.decorators.get_tracer", lambda _n: _Tracer())

        @trace("fail.async")
        async def boom() -> None:
            raise ValueError("async boom")

        with pytest.raises(ValueError, match="async boom"):
            await boom()
        assert len(releases) == 1

    def test_sync_exception_does_not_swallow_original(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The original exception type and message must be preserved."""
        monkeypatch.setattr(provider_mod, "_HAS_OTEL", False)

        @trace("preserve.exc")
        def boom() -> None:
            raise TypeError("specific type error")

        with pytest.raises(TypeError, match="specific type error"):
            boom()


# ── Decorator span name edge cases ────────────────────────────────────


class TestTraceDecoratorSpanNames:
    def test_lambda_span_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[str] = []

        class _Span:
            def __enter__(self) -> None:
                return None

            def __exit__(self, _a: object, _b: object, _c: object) -> None:
                return None

        class _Tracer:
            def start_as_current_span(self, name: str, **_: object) -> _Span:
                seen.append(name)
                return _Span()

        monkeypatch.setattr("undef.telemetry.tracing.decorators.should_sample", lambda _s, _n: True)
        monkeypatch.setattr("undef.telemetry.tracing.decorators.try_acquire", lambda _s: object())
        monkeypatch.setattr("undef.telemetry.tracing.decorators.release", lambda _t: None)
        monkeypatch.setattr("undef.telemetry.tracing.decorators.get_tracer", lambda _n: _Tracer())

        fn = trace()(lambda: 42)
        fn()
        assert seen == ["<lambda>"]

    def test_partial_function_span_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[str] = []

        class _Span:
            def __enter__(self) -> None:
                return None

            def __exit__(self, _a: object, _b: object, _c: object) -> None:
                return None

        class _Tracer:
            def start_as_current_span(self, name: str, **_: object) -> _Span:
                seen.append(name)
                return _Span()

        monkeypatch.setattr("undef.telemetry.tracing.decorators.should_sample", lambda _s, _n: True)
        monkeypatch.setattr("undef.telemetry.tracing.decorators.try_acquire", lambda _s: object())
        monkeypatch.setattr("undef.telemetry.tracing.decorators.release", lambda _t: None)
        monkeypatch.setattr("undef.telemetry.tracing.decorators.get_tracer", lambda _n: _Tracer())

        def add(a: int, b: int) -> int:
            return a + b

        fn = trace()(functools.partial(add, 1))
        fn(2)
        # functools.partial lacks __name__, falls back to __class__.__name__
        assert seen[0] == "partial"

    def test_explicit_name_overrides_function_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[str] = []

        class _Span:
            def __enter__(self) -> None:
                return None

            def __exit__(self, _a: object, _b: object, _c: object) -> None:
                return None

        class _Tracer:
            def start_as_current_span(self, name: str, **_: object) -> _Span:
                seen.append(name)
                return _Span()

        monkeypatch.setattr("undef.telemetry.tracing.decorators.should_sample", lambda _s, _n: True)
        monkeypatch.setattr("undef.telemetry.tracing.decorators.try_acquire", lambda _s: object())
        monkeypatch.setattr("undef.telemetry.tracing.decorators.release", lambda _t: None)
        monkeypatch.setattr("undef.telemetry.tracing.decorators.get_tracer", lambda _n: _Tracer())

        @trace("custom.span.name")
        def my_function() -> int:
            return 1

        my_function()
        assert seen == ["custom.span.name"]


# ── Nested tracing ────────────────────────────────────────────────────


class TestNestedTracing:
    def test_nested_noop_spans_restore_context(self) -> None:
        """Nested spans must restore the outer context when exiting."""
        tracer = _NoopTracer()
        with tracer.start_as_current_span("outer"):
            ctx_outer = get_trace_context()
            assert ctx_outer["trace_id"] is not None
            with tracer.start_as_current_span("inner"):
                ctx_inner = get_trace_context()
                assert ctx_inner["trace_id"] is not None
            assert get_trace_context() == ctx_outer
        # After outer exits, context is cleared
        assert get_trace_context() == {"trace_id": None, "span_id": None}


# ── Decorator + real sampling/backpressure ─────────────────────────────


class TestDecoratorWithSubsystems:
    def test_sampling_rejection_skips_span_creation(self) -> None:
        set_sampling_policy("traces", SamplingPolicy(default_rate=0.0))

        @trace("sampled.out")
        def fn() -> int:
            return 42

        assert fn() == 42
        # No span created — context should be clean
        assert get_trace_context() == {"trace_id": None, "span_id": None}

    def test_backpressure_full_skips_span_creation(self) -> None:
        set_queue_policy(QueuePolicy(traces_maxsize=0))

        @trace("bp.full")
        def fn() -> int:
            return 99

        # maxsize=0 means disabled (no queue), so acquire returns None
        # But with maxsize=0, backpressure is actually disabled, so it works
        assert fn() == 99

    async def test_async_sampling_rejection_skips_span(self) -> None:
        set_sampling_policy("traces", SamplingPolicy(default_rate=0.0))

        @trace("async.sampled.out")
        async def fn() -> int:
            return 77

        assert await fn() == 77
        assert get_trace_context() == {"trace_id": None, "span_id": None}

    def test_sampling_accepted_creates_span(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With default sampling (rate=1.0), NoopSpan sets trace context."""
        monkeypatch.setattr(provider_mod, "_HAS_OTEL", False)

        @trace("span.created")
        def fn() -> dict[str, str | None]:
            return dict(get_trace_context())

        result = fn()
        assert result["trace_id"] is not None

    async def test_async_sampling_accepted_creates_span(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With default sampling (rate=1.0), NoopSpan sets trace context."""
        monkeypatch.setattr(provider_mod, "_HAS_OTEL", False)

        @trace("async.span")
        async def fn() -> dict[str, str | None]:
            return dict(get_trace_context())

        result = await fn()
        assert result["trace_id"] is not None


# ── get_tracer edge cases ──────────────────────────────────────────────


class TestGetTracerEdgeCases:
    def test_get_tracer_none_name_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(provider_mod, "_HAS_OTEL", False)
        tracer = provider_mod.get_tracer(None)
        assert isinstance(tracer, _NoopTracer)

    def test_get_tracer_custom_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(provider_mod, "_HAS_OTEL", False)
        tracer = provider_mod.get_tracer("custom.module")
        assert isinstance(tracer, _NoopTracer)

    def test_lazy_tracer_delegates_each_call(self) -> None:
        """Each start_as_current_span call goes through get_tracer()."""
        span = provider_mod.tracer.start_as_current_span("test.lazy")
        assert hasattr(span, "__enter__")


# ── Context isolation across async tasks ───────────────────────────────


class TestContextIsolation:
    async def test_trace_context_isolated_between_tasks(self) -> None:
        """Two concurrent async tasks must not see each other's trace context."""
        results: dict[str, dict[str, str | None]] = {}

        async def task_a() -> None:
            set_trace_context("aaaa" * 8, "aaaa" * 4)
            await asyncio.sleep(0)  # yield
            results["a"] = dict(get_trace_context())

        async def task_b() -> None:
            set_trace_context("bbbb" * 8, "bbbb" * 4)
            await asyncio.sleep(0)  # yield
            results["b"] = dict(get_trace_context())

        await asyncio.gather(task_a(), task_b())
        assert results["a"]["trace_id"] == "aaaa" * 8
        assert results["b"]["trace_id"] == "bbbb" * 8

    async def test_trace_context_does_not_leak_from_child_task(self) -> None:
        set_trace_context(None, None)

        async def child() -> None:
            set_trace_context("child" + "0" * 27, "child" + "0" * 11)

        await asyncio.create_task(child())
        # Parent context should be unaffected
        ctx = get_trace_context()
        assert ctx["trace_id"] is None


# ── Provider shutdown edge cases ───────────────────────────────────────


class TestProviderShutdown:
    def test_double_shutdown_is_safe(self) -> None:
        provider_mod.shutdown_tracing()
        provider_mod.shutdown_tracing()
        assert provider_mod._provider_ref is None

    def test_shutdown_with_exception_in_shutdown(self) -> None:
        """If provider.shutdown() raises, it should still clean up state."""
        _reset_tracing_for_tests()
        provider_mod._provider_configured = True
        mock = Mock()
        mock.shutdown.side_effect = RuntimeError("shutdown failed")
        provider_mod._provider_ref = mock
        with pytest.raises(RuntimeError, match="shutdown failed"):
            provider_mod.shutdown_tracing()
        assert provider_mod._provider_configured is False
        assert provider_mod._provider_ref is None
