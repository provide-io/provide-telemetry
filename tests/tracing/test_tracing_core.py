# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import inspect
import warnings
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.tracing import get_trace_context, get_tracer, set_trace_context, trace
from provide.telemetry.tracing import provider as provider_mod
from provide.telemetry.tracing.provider import _reset_tracing_for_tests


def test_trace_context_helpers() -> None:
    set_trace_context("t1", "s1")
    assert get_trace_context() == {"trace_id": "t1", "span_id": "s1"}
    set_trace_context(None, None)


def test_noop_tracer_context() -> None:
    tracer = provider_mod._NoopTracer()
    with tracer.start_as_current_span("x") as span:
        assert span.name == "x"
        assert len(span.span_id) == 16
        ctx = get_trace_context()
        assert ctx["trace_id"] == "0" * 32
        assert ctx["span_id"] == "0" * 16
    assert get_trace_context() == {"trace_id": None, "span_id": None}


def test_get_tracer_without_otel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", False)
    t = get_tracer("x")
    assert isinstance(t, provider_mod._NoopTracer)


def test_get_tracer_with_otel(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_api = SimpleNamespace(get_tracer=Mock(return_value="otel-tracer"))
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)
    monkeypatch.setattr(provider_mod, "_provider_configured", True)
    monkeypatch.setattr(provider_mod, "_load_otel_trace_api", lambda: mock_api)
    assert cast(Any, get_tracer("x")) == "otel-tracer"
    get_tracer()
    mock_api.get_tracer.assert_any_call("provide.telemetry")
    assert None not in [args[0][0] for args in mock_api.get_tracer.call_args_list]
    assert provider_mod.get_tracer.__defaults__ == (None,)


def test_setup_tracing_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_tracing_for_tests()
    cfg = TelemetryConfig.from_env({"PROVIDE_TRACE_ENABLED": "false"})
    provider_mod.setup_tracing(cfg)  # disabled branch

    _reset_tracing_for_tests()
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", False)
    provider_mod.setup_tracing(TelemetryConfig())  # has_otel false branch

    _reset_tracing_for_tests()
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", False)
    provider_mod.setup_tracing(TelemetryConfig.from_env({"PROVIDE_TRACE_ENABLED": "true"}))
    assert provider_mod._provider_ref is None


def test_setup_tracing_short_circuits_when_otel_missing_even_if_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_tracing_for_tests()
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", False)

    def _boom_components() -> object:
        raise AssertionError("components loader should not be called")

    def _boom_api() -> object:
        raise AssertionError("api loader should not be called")

    monkeypatch.setattr(provider_mod, "_load_otel_tracing_components", _boom_components)
    monkeypatch.setattr(provider_mod, "_load_otel_trace_api", _boom_api)
    provider_mod.setup_tracing(TelemetryConfig.from_env({"PROVIDE_TRACE_ENABLED": "true"}))


def test_setup_tracing_already_configured_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_tracing_for_tests()
    provider_mod._provider_configured = True
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)
    provider_mod.setup_tracing(TelemetryConfig())
    assert provider_mod._provider_configured is True


def test_setup_tracing_with_otel_and_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_tracing_for_tests()
    provider = Mock()
    mock_otel = SimpleNamespace(set_tracer_provider=Mock(), get_tracer_provider=lambda: None)
    resource_cls = SimpleNamespace(create=Mock(return_value="res"))
    provider_cls = Mock(return_value=provider)
    processor_cls = Mock(return_value="processor")
    exporter_cls = Mock(return_value="exporter")
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)
    monkeypatch.setattr(provider_mod, "_load_otel_trace_api", lambda: mock_otel)
    monkeypatch.setattr(
        provider_mod,
        "_load_otel_tracing_components",
        lambda: (resource_cls, provider_cls, processor_cls, exporter_cls),
    )
    cfg = TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://trace"})
    provider_mod.setup_tracing(cfg)
    resource_cls.create.assert_called_once_with({"service.name": "provide-service", "service.version": "0.0.0"})
    provider_cls.assert_called_once_with(resource="res")
    exporter_cls.assert_called_once_with(endpoint="http://trace", headers={}, timeout=10.0)
    processor_cls.assert_called_once_with("exporter")
    provider.add_span_processor.assert_called_once_with("processor")
    mock_otel.set_tracer_provider.assert_called_once_with(provider)
    assert provider_mod._provider_ref is provider
    assert provider_mod._provider_configured is True


def test_setup_tracing_with_otel_without_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_tracing_for_tests()
    provider = Mock()
    mock_otel = SimpleNamespace(set_tracer_provider=Mock(), get_tracer_provider=lambda: None)
    resource_cls = SimpleNamespace(create=Mock(return_value="res"))
    provider_cls = Mock(return_value=provider)
    processor_cls = Mock(return_value="processor")
    exporter_cls = Mock(return_value="exporter")
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)
    monkeypatch.setattr(provider_mod, "_load_otel_trace_api", lambda: mock_otel)
    monkeypatch.setattr(
        provider_mod,
        "_load_otel_tracing_components",
        lambda: (resource_cls, provider_cls, processor_cls, exporter_cls),
    )
    cfg = TelemetryConfig.from_env({})
    provider_mod.setup_tracing(cfg)
    resource_cls.create.assert_called_once_with({"service.name": "provide-service", "service.version": "0.0.0"})
    provider_cls.assert_called_once_with(resource="res")
    mock_otel.set_tracer_provider.assert_called_once_with(provider)
    provider.add_span_processor.assert_not_called()


def test_setup_tracing_with_missing_components(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_tracing_for_tests()
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)
    monkeypatch.setattr(provider_mod, "_load_otel_tracing_components", lambda: None)
    monkeypatch.setattr(provider_mod, "_load_otel_trace_api", lambda: None)
    provider_mod.setup_tracing(TelemetryConfig())
    assert provider_mod._provider_configured is False


def test_setup_tracing_endpoint_with_resilience_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_tracing_for_tests()
    provider = Mock()
    mock_otel = SimpleNamespace(set_tracer_provider=Mock(), get_tracer_provider=lambda: None)
    resource_cls = SimpleNamespace(create=Mock(return_value="res"))
    provider_cls = Mock(return_value=provider)
    processor_cls = Mock(return_value="processor")
    exporter_cls = Mock(return_value="exporter")
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)
    monkeypatch.setattr(provider_mod, "_load_otel_trace_api", lambda: mock_otel)
    monkeypatch.setattr(
        provider_mod,
        "_load_otel_tracing_components",
        lambda: (resource_cls, provider_cls, processor_cls, exporter_cls),
    )
    from provide.telemetry import resilience as resilience_mod

    monkeypatch.setattr(resilience_mod, "run_with_resilience", lambda _signal, _op: None)
    cfg = TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://trace"})
    provider_mod.setup_tracing(cfg)
    provider.add_span_processor.assert_not_called()

    _reset_tracing_for_tests()
    monkeypatch.setattr(provider_mod, "_load_otel_tracing_components", lambda: (object(), object(), object(), object()))
    monkeypatch.setattr(provider_mod, "_load_otel_trace_api", lambda: None)
    provider_mod.setup_tracing(TelemetryConfig())
    assert provider_mod._provider_configured is False


def test_shutdown_tracing_calls_provider_shutdown() -> None:
    _reset_tracing_for_tests()
    provider_mod._provider_configured = True
    provider = Mock()
    provider_mod._provider_ref = provider
    provider_mod.shutdown_tracing()
    provider.shutdown.assert_called_once()
    assert provider_mod._provider_ref is None
    assert provider_mod._provider_configured is False


def test_shutdown_tracing_provider_absent_and_noncallable() -> None:
    _reset_tracing_for_tests()
    provider_mod._provider_configured = True
    provider_mod.shutdown_tracing()
    assert provider_mod._provider_ref is None
    assert provider_mod._provider_configured is False

    provider_mod._provider_configured = True
    provider_mod._provider_ref = SimpleNamespace(shutdown="nope")
    provider_mod.shutdown_tracing()
    assert provider_mod._provider_ref is None
    assert provider_mod._provider_configured is False

    provider_mod._provider_configured = True
    provider_mod._provider_ref = SimpleNamespace()
    provider_mod.shutdown_tracing()
    assert provider_mod._provider_ref is None
    assert provider_mod._provider_configured is False


def test_trace_decorator_sync_and_async() -> None:
    @trace("a.b.c")
    def fn(x: int) -> int:
        return x + 1

    assert fn(1) == 2

    @trace("a.b.c")
    async def afn(x: int) -> int:
        return x + 2

    import asyncio

    assert asyncio.run(afn(1)) == 3


def test_trace_decorator_span_name_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str | None] = []

    class _Span:
        def __enter__(self) -> None:
            return None

        def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
            return None

    class _Tracer:
        def start_as_current_span(self, name: str | None, **_: object) -> _Span:
            seen.append(name)
            return _Span()

    monkeypatch.setattr("provide.telemetry.tracing.decorators.get_tracer", lambda _name: _Tracer())
    monkeypatch.setattr("provide.telemetry.sampling.should_sample", lambda _signal, _name: True)
    monkeypatch.setattr("provide.telemetry.backpressure.try_acquire", lambda _signal: object())
    monkeypatch.setattr("provide.telemetry.backpressure.release", lambda _ticket: None)

    @trace()
    def fn_default() -> int:
        return 1

    @trace("explicit.name")
    async def fn_named() -> int:
        return 2

    assert fn_default() == 1
    import asyncio

    assert asyncio.run(fn_named()) == 2
    assert seen == ["fn_default", "explicit.name"]


def test_trace_decorator_span_name_for_callable_object(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str | None] = []

    class _Span:
        def __enter__(self) -> None:
            return None

        def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
            return None

    class _Tracer:
        def start_as_current_span(self, name: str | None, **_: object) -> _Span:
            seen.append(name)
            return _Span()

    class _Callable:
        def __call__(self) -> int:
            return 7

    monkeypatch.setattr("provide.telemetry.tracing.decorators.get_tracer", lambda _name: _Tracer())
    monkeypatch.setattr("provide.telemetry.sampling.should_sample", lambda _signal, _name: True)
    monkeypatch.setattr("provide.telemetry.backpressure.try_acquire", lambda _signal: object())
    monkeypatch.setattr("provide.telemetry.backpressure.release", lambda _ticket: None)
    wrapped = trace()(_Callable())
    assert wrapped() == 7
    assert seen == ["_Callable"]


def test_trace_async_preserves_context_across_await(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", False)
    monkeypatch.setattr("provide.telemetry.sampling.should_sample", lambda _signal, _name: True)
    monkeypatch.setattr("provide.telemetry.backpressure.try_acquire", lambda _signal: object())
    monkeypatch.setattr("provide.telemetry.backpressure.release", lambda _ticket: None)

    @trace("async.context")
    async def afn() -> tuple[str | None, str | None]:
        before = get_trace_context()
        import asyncio

        await asyncio.sleep(0)
        after = get_trace_context()
        assert before == after
        return before["trace_id"], before["span_id"]

    import asyncio

    trace_id, span_id = asyncio.run(afn())
    assert trace_id == "0" * 32
    assert span_id == "0" * 16
    assert get_trace_context() == {"trace_id": None, "span_id": None}


def test_trace_async_detection_uses_inspect_without_deprecation_warning() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)

        @trace("a.b.c")
        async def afn() -> int:
            return 1

        assert inspect.iscoroutinefunction(afn)

    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deprecations == []


def test_trace_decorator_sampling_and_backpressure_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("provide.telemetry.sampling.should_sample", lambda _signal, _name: False)

    @trace("sampled.out")
    def sampled_out() -> int:
        return 1

    assert sampled_out() == 1

    monkeypatch.setattr("provide.telemetry.sampling.should_sample", lambda _signal, _name: True)
    monkeypatch.setattr("provide.telemetry.backpressure.try_acquire", lambda _signal: None)

    @trace("queue.drop")
    def queue_drop() -> int:
        return 2

    assert queue_drop() == 2


def test_trace_decorator_releases_backpressure_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    releases: list[object] = []

    class _Span:
        def __enter__(self) -> None:
            return None

        def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
            return None

    class _Tracer:
        def start_as_current_span(self, _name: str, **_: object) -> _Span:
            return _Span()

    monkeypatch.setattr("provide.telemetry.sampling.should_sample", lambda _signal, _name: True)
    monkeypatch.setattr("provide.telemetry.backpressure.try_acquire", lambda _signal: object())
    monkeypatch.setattr("provide.telemetry.backpressure.release", lambda ticket: releases.append(ticket))
    monkeypatch.setattr("provide.telemetry.tracing.decorators.get_tracer", lambda _name: _Tracer())

    @trace("ticket.release")
    def with_ticket() -> int:
        return 7

    assert with_ticket() == 7
    assert len(releases) == 1


def test_trace_decorator_async_sampling_and_queue_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    monkeypatch.setattr("provide.telemetry.sampling.should_sample", lambda _signal, _name: False)

    @trace("async.sampled.out")
    async def sampled_out() -> int:
        return 11

    assert asyncio.run(sampled_out()) == 11

    monkeypatch.setattr("provide.telemetry.sampling.should_sample", lambda _signal, _name: True)
    monkeypatch.setattr("provide.telemetry.backpressure.try_acquire", lambda _signal: None)

    @trace("async.queue.drop")
    async def queue_drop() -> int:
        return 12

    assert asyncio.run(queue_drop()) == 12
