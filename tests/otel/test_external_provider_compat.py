# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests proving externally installed OTel providers are honored by get_tracer/get_meter.

These tests use monkeypatching rather than installing real OTel providers because
the OTel Python SDK only allows set_tracer_provider/set_meter_provider once per
process; subsequent calls are silently ignored, making test isolation impossible
when using the real global API.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.otel


# ── get_tracer() external-provider path ────────────────────────────────


class TestExternalTracerProvider:
    def test_get_tracer_uses_externally_installed_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When _otel_global_set is False and the OTel global is a real SDK provider,
        get_tracer() returns a real tracer instead of a NoopTracer."""
        from provide.telemetry.tracing import provider as pmod

        class FakeTracer:
            def start_as_current_span(self, name: str, **kw: object) -> object:
                return contextlib.nullcontext()

        class FakeSDKProvider:  # name has neither "Proxy" nor "NoOp"
            pass

        fake_api = SimpleNamespace(
            get_tracer_provider=lambda: FakeSDKProvider(),
            get_tracer=lambda _name: FakeTracer(),
        )
        monkeypatch.setattr(pmod, "_provider_configured", False)
        monkeypatch.setattr(pmod, "_otel_global_set", False)
        monkeypatch.setattr(pmod, "_baseline_captured", False)
        monkeypatch.setattr(pmod, "_load_otel_trace_api", lambda: fake_api)

        tracer = pmod.get_tracer("external.test")
        assert not isinstance(tracer, pmod._NoopTracer)

    def test_get_tracer_noop_when_global_is_default_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When the OTel global is the same object as the captured baseline (identity match),
        get_tracer() returns NoopTracer — nobody has installed a real provider."""
        from provide.telemetry.tracing import provider as pmod

        sentinel = object()  # simulates the default placeholder provider
        fake_api = SimpleNamespace(get_tracer_provider=lambda: sentinel)
        monkeypatch.setattr(pmod, "_provider_configured", False)
        monkeypatch.setattr(pmod, "_otel_global_set", False)
        monkeypatch.setattr(pmod, "_baseline_captured", True)
        monkeypatch.setattr(pmod, "_baseline_tracer_provider", sentinel)
        monkeypatch.setattr(pmod, "_load_otel_trace_api", lambda: fake_api)

        tracer = pmod.get_tracer()
        assert isinstance(tracer, pmod._NoopTracer)

    def test_get_tracer_noop_when_proxy_provider_before_setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Before setup_tracing() captures a baseline, a ProxyTracerProvider
        should be treated as a placeholder (returns NoopTracer)."""
        from undef.telemetry.tracing import provider as pmod

        class ProxyTracerProvider:
            pass

        fake_api = SimpleNamespace(get_tracer_provider=lambda: ProxyTracerProvider())
        monkeypatch.setattr(pmod, "_provider_configured", False)
        monkeypatch.setattr(pmod, "_otel_global_set", False)
        monkeypatch.setattr(pmod, "_baseline_captured", False)
        monkeypatch.setattr(pmod, "_load_otel_trace_api", lambda: fake_api)

        tracer = pmod.get_tracer()
        assert isinstance(tracer, pmod._NoopTracer)

    def test_get_tracer_real_when_external_provider_before_setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Before setup_tracing() is called, if an external caller installed a real
        (non-Proxy) provider, get_tracer() returns a real tracer."""
        from undef.telemetry.tracing import provider as pmod

        class FakeTracer:
            def start_as_current_span(self, name: str, **kw: object) -> object:
                return contextlib.nullcontext()

        class RealTracerProvider:  # no "Proxy" in name
            pass

        fake_api = SimpleNamespace(
            get_tracer_provider=lambda: RealTracerProvider(),
            get_tracer=lambda _name: FakeTracer(),
        )
        monkeypatch.setattr(pmod, "_provider_configured", False)
        monkeypatch.setattr(pmod, "_otel_global_set", False)
        monkeypatch.setattr(pmod, "_baseline_captured", False)
        monkeypatch.setattr(pmod, "_load_otel_trace_api", lambda: fake_api)

        tracer = pmod.get_tracer("ext")
        assert not isinstance(tracer, pmod._NoopTracer)

    def test_get_tracer_noop_after_our_provider_shut_down(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When _otel_global_set is True (we shut down our provider), get_tracer()
        returns NoopTracer even if OTel global still holds a real provider object."""
        from provide.telemetry.tracing import provider as pmod

        class FakeSDKProvider:
            pass

        fake_api = SimpleNamespace(
            get_tracer_provider=lambda: FakeSDKProvider(),
            get_tracer=lambda _name: object(),
        )
        monkeypatch.setattr(pmod, "_provider_configured", False)
        monkeypatch.setattr(pmod, "_otel_global_set", True)  # our provider shut down
        monkeypatch.setattr(pmod, "_load_otel_trace_api", lambda: fake_api)

        tracer = pmod.get_tracer()
        assert isinstance(tracer, pmod._NoopTracer)


# ── get_meter() external-provider path ────────────────────────────────


class TestExternalMeterProvider:
    def test_get_meter_uses_externally_installed_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When _meter_global_set is False and the OTel global is a real SDK provider,
        get_meter() returns a real meter instead of None."""
        from provide.telemetry.metrics import provider as mpmod

        class FakeMeter:
            pass

        class FakeSDKMeterProvider:  # neither "Proxy" nor "NoOp"
            pass

        fake_api = SimpleNamespace(
            get_meter_provider=lambda: FakeSDKMeterProvider(),
            get_meter=lambda _name: FakeMeter(),
        )
        monkeypatch.setattr(mpmod, "_meter_provider", None)
        monkeypatch.setattr(mpmod, "_meter_global_set", False)
        monkeypatch.setattr(mpmod, "_baseline_captured", False)
        monkeypatch.setattr(mpmod, "_load_otel_metrics_api", lambda: fake_api)

        meter = mpmod.get_meter("external.test")
        assert type(meter).__name__ == "FakeMeter"

    def test_get_meter_none_when_global_is_default_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When the OTel global is the same object as the captured baseline (identity match),
        get_meter() returns None — nobody has installed a real provider."""
        from provide.telemetry.metrics import provider as mpmod

        sentinel = object()  # simulates the default placeholder provider
        fake_api = SimpleNamespace(get_meter_provider=lambda: sentinel)
        monkeypatch.setattr(mpmod, "_meter_provider", None)
        monkeypatch.setattr(mpmod, "_meter_global_set", False)
        monkeypatch.setattr(mpmod, "_baseline_captured", True)
        monkeypatch.setattr(mpmod, "_baseline_meter_provider", sentinel)
        monkeypatch.setattr(mpmod, "_load_otel_metrics_api", lambda: fake_api)

        meter = mpmod.get_meter()
        assert meter is None

    def test_get_meter_none_when_proxy_provider_before_setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Before setup_metrics() captures a baseline, a ProxyMeterProvider
        should be treated as a placeholder (returns None)."""
        from undef.telemetry.metrics import provider as mpmod

        class ProxyMeterProvider:
            pass

        fake_api = SimpleNamespace(get_meter_provider=lambda: ProxyMeterProvider())
        monkeypatch.setattr(mpmod, "_meter_provider", None)
        monkeypatch.setattr(mpmod, "_meter_global_set", False)
        monkeypatch.setattr(mpmod, "_baseline_captured", False)
        monkeypatch.setattr(mpmod, "_load_otel_metrics_api", lambda: fake_api)

        meter = mpmod.get_meter()
        assert meter is None

    def test_get_meter_real_when_external_provider_before_setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Before setup_metrics() is called, if an external caller installed a real
        (non-Proxy) provider, get_meter() returns a real meter."""
        from undef.telemetry.metrics import provider as mpmod

        class RealMeterProvider:  # no "Proxy" in name
            pass

        fake_api = SimpleNamespace(
            get_meter_provider=lambda: RealMeterProvider(),
            get_meter=lambda _name: "real-meter",
        )
        monkeypatch.setattr(mpmod, "_meter_provider", None)
        monkeypatch.setattr(mpmod, "_meter_global_set", False)
        monkeypatch.setattr(mpmod, "_baseline_captured", False)
        monkeypatch.setattr(mpmod, "_load_otel_metrics_api", lambda: fake_api)

        meter = mpmod.get_meter("ext")
        assert meter == "real-meter"

    def test_get_meter_none_after_our_provider_shut_down(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When _meter_global_set is True (we shut down our provider), get_meter()
        returns None even if OTel global still holds a real provider object."""
        from provide.telemetry.metrics import provider as mpmod

        class FakeSDKMeterProvider:
            pass

        fake_api = SimpleNamespace(
            get_meter_provider=lambda: FakeSDKMeterProvider(),
            get_meter=lambda _name: object(),
        )
        monkeypatch.setattr(mpmod, "_meter_provider", None)
        monkeypatch.setattr(mpmod, "_meter_global_set", True)  # our provider shut down
        monkeypatch.setattr(mpmod, "_load_otel_metrics_api", lambda: fake_api)

        meter = mpmod.get_meter()
        assert meter is None
