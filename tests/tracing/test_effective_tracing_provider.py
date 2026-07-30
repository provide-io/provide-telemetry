# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""_has_effective_tracing_provider — "is a provider in play", not "did we install one".

A host application running its own OTel SDK owns the tracer global without ever
calling setup_telemetry(); get_tracer() already resolves that provider, so spans
export through it and its sampler is the sampling authority. The facade must not
apply its own probabilistic gate on top.

No OTel extra required: the trace API is monkeypatched throughout, which also
keeps these tests inside the mutation gate's non-otel selection.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from typing import cast

import pytest

from provide.telemetry.health import get_health_snapshot, reset_health_for_tests
from provide.telemetry.sampling import SamplingPolicy, set_sampling_policy
from provide.telemetry.tracing import provider as pmod
from provide.telemetry.tracing.decorators import trace


def _signal(status: dict[str, object], section: str, signal: str) -> object:
    """Read status[section][signal].

    get_runtime_status() is typed dict[str, object] for cross-language shape
    parity, so the nested read needs narrowing rather than a type: ignore —
    mypy accepts the ignore, ty does not.
    """
    return cast("dict[str, object]", status[section])[signal]


class _FakeTracer:
    def start_as_current_span(self, name: str, **kw: object) -> object:
        return contextlib.nullcontext()


class _ExternalProvider:
    """Shaped like an SDK provider: carries the force_flush/shutdown pair."""

    def force_flush(self, *_a: object, **_k: object) -> None: ...

    def shutdown(self, *_a: object, **_k: object) -> None: ...


class _ProxyTracerProvider:
    pass


def _fake_trace_api(provider: object) -> SimpleNamespace:
    """A fake OTel trace API whose global tracer provider is ``provider``."""
    return SimpleNamespace(
        get_tracer_provider=lambda: provider,
        get_tracer=lambda _name: _FakeTracer(),
        get_current_span=lambda: SimpleNamespace(get_span_context=lambda: SimpleNamespace(trace_id=0, span_id=0)),
    )


def _install_trace_global(monkeypatch: pytest.MonkeyPatch, provider: object) -> None:
    """Put ``provider`` on the trace global with no setup_tracing() history of our own."""
    monkeypatch.setattr(pmod, "_provider_configured", False)
    monkeypatch.setattr(pmod, "_provider_ref", None)
    monkeypatch.setattr(pmod, "_otel_global_set", False)
    monkeypatch.setattr(pmod, "_tracing_explicitly_disabled", False)
    monkeypatch.setattr(pmod, "_load_otel_trace_api", lambda: _fake_trace_api(provider))


class TestEffectiveTracingProviderProbe:
    def test_true_for_our_own_provider_without_consulting_the_global(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Our own provider ref answers on its own — no OTel API resolution required."""
        monkeypatch.setattr(pmod, "_provider_ref", object())
        monkeypatch.setattr(pmod, "_load_otel_trace_api", lambda: None)
        assert pmod._has_effective_tracing_provider() is True

    def test_false_when_the_otel_api_is_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pmod, "_provider_ref", None)
        monkeypatch.setattr(pmod, "_load_otel_trace_api", lambda: None)
        assert pmod._has_effective_tracing_provider() is False

    def test_true_for_a_provider_a_host_installed_itself(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_trace_global(monkeypatch, _ExternalProvider())
        # We installed nothing, so the install-scoped predicate still says no.
        assert pmod._has_live_tracing_provider() is False
        assert pmod._has_effective_tracing_provider() is True

    def test_false_when_the_global_is_the_api_placeholder(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_trace_global(monkeypatch, _ProxyTracerProvider())
        assert pmod._has_effective_tracing_provider() is False

    def test_false_after_our_own_provider_was_shut_down(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_trace_global(monkeypatch, _ExternalProvider())
        monkeypatch.setattr(pmod, "_otel_global_set", True)
        assert pmod._has_effective_tracing_provider() is False


class TestExternalProviderOwnsSampling:
    def test_facade_sampling_is_skipped_when_a_host_provider_owns_the_global(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rate 0 must not drop the span: the host SDK's sampler is authoritative."""
        _install_trace_global(monkeypatch, _ExternalProvider())
        set_sampling_policy("traces", SamplingPolicy(default_rate=0.0))
        reset_health_for_tests()

        @trace("external.owned.span")
        def work() -> str:
            return "ok"

        assert work() == "ok"
        snapshot = get_health_snapshot()
        assert snapshot.emitted_traces == 1
        assert snapshot.dropped_traces == 0

    def test_facade_sampling_applies_when_no_provider_owns_the_global(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_trace_global(monkeypatch, _ProxyTracerProvider())
        set_sampling_policy("traces", SamplingPolicy(default_rate=0.0))
        reset_health_for_tests()

        @trace("facade.only.span")
        def work() -> str:
            return "ok"

        assert work() == "ok"
        snapshot = get_health_snapshot()
        assert snapshot.emitted_traces == 0
        assert snapshot.dropped_traces == 1


class TestRuntimeStatusReportsHostProvider:
    def test_status_reports_a_host_tracer_provider_as_installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from provide.telemetry.runtime import get_runtime_status

        _install_trace_global(monkeypatch, _ExternalProvider())
        status = get_runtime_status()
        assert _signal(status, "providers", "traces") is True
        assert _signal(status, "fallback", "traces") is False

    def test_status_reports_fallback_when_only_the_placeholder_is_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from provide.telemetry.runtime import get_runtime_status

        _install_trace_global(monkeypatch, _ProxyTracerProvider())
        status = get_runtime_status()
        assert _signal(status, "providers", "traces") is False
        assert _signal(status, "fallback", "traces") is True


def test_false_when_tracing_is_explicitly_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """A disabled signal has no provider in play, however live the global is.

    get_tracer() checks _tracing_explicitly_disabled before anything else. When
    the probe skipped it, @trace bypassed facade sampling for spans get_tracer()
    then served from a _NoopTracer: nothing exported, but counted as emitted and
    holding a backpressure ticket.
    """
    _install_trace_global(monkeypatch, _ExternalProvider())
    monkeypatch.setattr(pmod, "_tracing_explicitly_disabled", True)
    assert pmod._has_effective_tracing_provider() is False


def test_disabled_tracing_still_applies_facade_sampling(monkeypatch: pytest.MonkeyPatch) -> None:
    """The user-visible half: rate 0 must still drop when tracing is disabled."""
    _install_trace_global(monkeypatch, _ExternalProvider())
    monkeypatch.setattr(pmod, "_tracing_explicitly_disabled", True)
    set_sampling_policy("traces", SamplingPolicy(default_rate=0.0))
    reset_health_for_tests()

    @trace("disabled.signal.span")
    def work() -> str:
        return "ok"

    assert work() == "ok"
    assert get_health_snapshot().emitted_traces == 0
    assert get_health_snapshot().dropped_traces == 1


@pytest.mark.otel
class TestAdoptedProviderActuallyExports:
    """Status is not export. These assert a span reaches the host's exporter.

    The probe tests above prove the facade *reports* a host-installed provider,
    and the cross-language ``host_provider_adoption`` case proves all four agree
    on that reporting. Neither shows a span leaving through it. Go had this
    covered (``TestAdopt_UsesAHostInstalledTracerProvider``); Python, TypeScript
    and Rust asserted status or sampling only, so a regression that reported
    adoption while emitting nowhere would have gone unnoticed.
    """

    def test_a_span_reaches_a_host_installed_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pytest.importorskip("opentelemetry.sdk.trace")
        from opentelemetry import trace as otel_trace_api
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        from provide.telemetry.tracing.decorators import trace

        exporter = InMemorySpanExporter()
        host_provider = TracerProvider()
        host_provider.add_span_processor(SimpleSpanProcessor(exporter))

        # A provider the host installed; we install nothing of our own. The
        # fake API delegates get_tracer to the real provider rather than
        # returning a stub, so the span genuinely travels the host's pipeline —
        # a stub tracer would make this test pass while exporting nothing, which
        # is the exact failure it exists to catch.
        monkeypatch.setattr(pmod, "_provider_configured", False)
        monkeypatch.setattr(pmod, "_provider_ref", None)
        monkeypatch.setattr(pmod, "_otel_global_set", False)
        monkeypatch.setattr(pmod, "_tracing_explicitly_disabled", False)
        monkeypatch.setattr(
            pmod,
            "_load_otel_trace_api",
            lambda: SimpleNamespace(
                get_tracer_provider=lambda: host_provider,
                get_tracer=host_provider.get_tracer,
                get_current_span=otel_trace_api.get_current_span,
            ),
        )

        @trace("adopted.export.span")
        def _work() -> int:
            return 7

        assert _work() == 7

        spans = exporter.get_finished_spans()
        assert [span.name for span in spans] == ["adopted.export.span"], (
            "the facade reported the host provider as in play but no span reached its exporter"
        )
