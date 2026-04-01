# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Regression tests for code review issues (batch 2): lazy resolution,
double-checked locking, circuit breaker, shutdown reset, force-reconfigure."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.health import reset_health_for_tests
from provide.telemetry.resilience import (
    reset_resilience_for_tests,
)


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    reset_health_for_tests()
    reset_resilience_for_tests()


# ── Issue #15: fallback instruments lazy-resolve after provider setup ──


class TestFallbackLazyResolve:
    def test_counter_resolves_otel_after_provider_setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Counter._resolve_otel() binds to real OTel instrument when provider becomes available."""
        from provide.telemetry.metrics.fallback import Counter

        c = Counter("test.counter")
        assert c._otel_counter is None
        assert c._resolved is False

        mock_counter = Mock()
        mock_meter = Mock()
        mock_meter.create_counter.return_value = mock_counter
        monkeypatch.setattr("provide.telemetry.metrics.provider.get_meter", lambda: mock_meter)

        result = c._resolve_otel()
        assert result is mock_counter
        assert c._resolved is True
        mock_meter.create_counter.assert_called_once_with(name="test.counter")

    def test_gauge_resolves_otel_after_provider_setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from provide.telemetry.metrics.fallback import Gauge

        g = Gauge("test.gauge")
        assert g._resolved is False

        mock_gauge = Mock()
        mock_meter = Mock()
        mock_meter.create_up_down_counter.return_value = mock_gauge
        monkeypatch.setattr("provide.telemetry.metrics.provider.get_meter", lambda: mock_meter)

        result = g._resolve_otel()
        assert result is mock_gauge
        assert g._resolved is True
        mock_meter.create_up_down_counter.assert_called_once_with(name="test.gauge")

    def test_histogram_resolves_otel_after_provider_setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from provide.telemetry.metrics.fallback import Histogram

        h = Histogram("test.histo")
        assert h._resolved is False

        mock_histo = Mock()
        mock_meter = Mock()
        mock_meter.create_histogram.return_value = mock_histo
        monkeypatch.setattr("provide.telemetry.metrics.provider.get_meter", lambda: mock_meter)

        result = h._resolve_otel()
        assert result is mock_histo
        assert h._resolved is True
        mock_meter.create_histogram.assert_called_once_with(name="test.histo")

    def test_counter_resolve_returns_none_when_no_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from provide.telemetry.metrics.fallback import Counter

        c = Counter("test.counter")
        monkeypatch.setattr("provide.telemetry.metrics.provider.get_meter", lambda: None)
        result = c._resolve_otel()
        assert result is None
        assert c._resolved is False

    def test_counter_resolve_handles_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from provide.telemetry.metrics.fallback import Counter

        c = Counter("test.counter")
        mock_meter = Mock()
        mock_meter.create_counter.side_effect = RuntimeError("oops")
        monkeypatch.setattr("provide.telemetry.metrics.provider.get_meter", lambda: mock_meter)

        result = c._resolve_otel()
        assert result is None
        assert c._resolved is True  # marked resolved to avoid retry

    def test_resolve_skips_when_already_resolved(self) -> None:
        from provide.telemetry.metrics.fallback import Counter

        mock_counter = Mock()
        c = Counter("test.counter", otel_counter=mock_counter)
        assert c._resolved is True
        result = c._resolve_otel()
        assert result is mock_counter

    def test_gauge_resolve_no_provider_and_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from provide.telemetry.metrics.fallback import Gauge

        g = Gauge("test.gauge")
        monkeypatch.setattr("provide.telemetry.metrics.provider.get_meter", lambda: None)
        assert g._resolve_otel() is None
        # Now test exception path
        g2 = Gauge("test.gauge2")
        mock_meter = Mock()
        mock_meter.create_up_down_counter.side_effect = RuntimeError("oops")
        monkeypatch.setattr("provide.telemetry.metrics.provider.get_meter", lambda: mock_meter)
        assert g2._resolve_otel() is None
        assert g2._resolved is True

    def test_histogram_resolve_no_provider_and_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from provide.telemetry.metrics.fallback import Histogram

        h = Histogram("test.histo")
        monkeypatch.setattr("provide.telemetry.metrics.provider.get_meter", lambda: None)
        assert h._resolve_otel() is None
        h2 = Histogram("test.histo2")
        mock_meter = Mock()
        mock_meter.create_histogram.side_effect = RuntimeError("oops")
        monkeypatch.setattr("provide.telemetry.metrics.provider.get_meter", lambda: mock_meter)
        assert h2._resolve_otel() is None
        assert h2._resolved is True


# ── Issue #16: double-checked locking race in provider setup ───────────


class TestProviderDoubleCheckLocking:
    def test_metrics_setup_discards_when_another_thread_won(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If _meter_provider is set between the two lock acquisitions, discard the new provider."""

        from provide.telemetry.metrics import provider as prov_mod
        from provide.telemetry.metrics.provider import _set_meter_for_test, setup_metrics

        _set_meter_for_test(None)
        monkeypatch.setattr(prov_mod, "_HAS_OTEL_METRICS", True)

        fake_otel = Mock()
        fake_otel.get_meter.return_value = Mock()
        monkeypatch.setattr(prov_mod, "_load_otel_metrics_api", lambda: fake_otel)

        # Use object without shutdown method to cover the not-callable branch
        bare_provider = type("P", (), {})()
        provider_cls = Mock(return_value=bare_provider)
        resource_cls = Mock()
        resource_cls.create.return_value = "res"
        monkeypatch.setattr(
            prov_mod,
            "_load_otel_metrics_components",
            lambda: (provider_cls, resource_cls, Mock(), Mock()),
        )

        real_lock = prov_mod._meter_lock
        call_count = {"n": 0}

        class _InterceptLock:
            def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
                result = real_lock.acquire(blocking, timeout)
                call_count["n"] += 1
                if call_count["n"] == 2:
                    prov_mod._meter_provider = "winner"
                return result

            def release(self) -> None:
                real_lock.release()

            def __enter__(self) -> _InterceptLock:
                self.acquire()
                return self

            def __exit__(self, *a: object) -> None:
                self.release()

        monkeypatch.setattr(prov_mod, "_meter_lock", _InterceptLock())
        cfg = TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://test"})
        setup_metrics(cfg)
        assert prov_mod._meter_provider == "winner"
        monkeypatch.setattr(prov_mod, "_meter_lock", real_lock)
        _set_meter_for_test(None)

    def test_metrics_race_loser_with_shutdown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When the race-loser has a shutdown method, it must be called."""
        from provide.telemetry.metrics import provider as prov_mod
        from provide.telemetry.metrics.provider import _set_meter_for_test, setup_metrics

        _set_meter_for_test(None)
        monkeypatch.setattr(prov_mod, "_HAS_OTEL_METRICS", True)
        fake_otel, mock_provider = Mock(), Mock()
        fake_otel.get_meter.return_value = Mock()
        monkeypatch.setattr(prov_mod, "_load_otel_metrics_api", lambda: fake_otel)
        monkeypatch.setattr(
            prov_mod,
            "_load_otel_metrics_components",
            lambda: (Mock(return_value=mock_provider), Mock(create=Mock(return_value="r")), Mock(), Mock()),
        )
        real_lock = prov_mod._meter_lock
        call_count = {"n": 0}

        class _IL:
            def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
                r = real_lock.acquire(blocking, timeout)
                call_count["n"] += 1
                if call_count["n"] == 2:
                    prov_mod._meter_provider = "winner"
                return r

            def release(self) -> None:
                real_lock.release()

            def __enter__(self) -> _IL:
                self.acquire()
                return self

            def __exit__(self, *a: object) -> None:
                self.release()

        monkeypatch.setattr(prov_mod, "_meter_lock", _IL())
        setup_metrics(TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://x"}))
        mock_provider.shutdown.assert_called_once()
        monkeypatch.setattr(prov_mod, "_meter_lock", real_lock)
        _set_meter_for_test(None)

    def test_tracing_setup_discards_when_another_thread_won(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from provide.telemetry.tracing import provider as tprov_mod
        from provide.telemetry.tracing.provider import _reset_tracing_for_tests, setup_tracing

        _reset_tracing_for_tests()
        monkeypatch.setattr(tprov_mod, "_HAS_OTEL", True)

        fake_trace = Mock()
        monkeypatch.setattr(tprov_mod, "_load_otel_trace_api", lambda: fake_trace)

        # Provider with add_span_processor but no shutdown
        bare_provider = type("P", (), {"add_span_processor": lambda self, p: None})()
        provider_cls = Mock(return_value=bare_provider)
        resource_cls = Mock()
        resource_cls.create.return_value = "res"
        monkeypatch.setattr(
            tprov_mod,
            "_load_otel_tracing_components",
            lambda: (resource_cls, provider_cls, Mock(), Mock()),
        )

        real_lock = tprov_mod._provider_lock
        call_count = {"n": 0}

        class _InterceptLock:
            def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
                result = real_lock.acquire(blocking, timeout)
                call_count["n"] += 1
                if call_count["n"] == 2:
                    tprov_mod._provider_configured = True
                    tprov_mod._provider_ref = "winner"
                return result

            def release(self) -> None:
                real_lock.release()

            def __enter__(self) -> _InterceptLock:
                self.acquire()
                return self

            def __exit__(self, *a: object) -> None:
                self.release()

        monkeypatch.setattr(tprov_mod, "_provider_lock", _InterceptLock())
        cfg = TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://test"})
        setup_tracing(cfg)
        assert tprov_mod._provider_ref == "winner"
        monkeypatch.setattr(tprov_mod, "_provider_lock", real_lock)
        _reset_tracing_for_tests()

    def test_tracing_race_loser_with_shutdown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from provide.telemetry.tracing import provider as tp
        from provide.telemetry.tracing.provider import _reset_tracing_for_tests, setup_tracing

        _reset_tracing_for_tests()
        monkeypatch.setattr(tp, "_HAS_OTEL", True)
        monkeypatch.setattr(tp, "_load_otel_trace_api", lambda: Mock())
        mp = Mock()
        monkeypatch.setattr(
            tp,
            "_load_otel_tracing_components",
            lambda: (Mock(create=Mock(return_value="r")), Mock(return_value=mp), Mock(), Mock()),
        )
        rl = tp._provider_lock
        cc = {"n": 0}

        class _IL:
            def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
                r = rl.acquire(blocking, timeout)
                cc["n"] += 1
                if cc["n"] == 2:
                    tp._provider_configured = True
                    tp._provider_ref = "w"
                return r

            def release(self) -> None:
                rl.release()

            def __enter__(self) -> _IL:
                self.acquire()
                return self

            def __exit__(self, *a: object) -> None:
                self.release()

        monkeypatch.setattr(tp, "_provider_lock", _IL())
        setup_tracing(TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://x"}))
        mp.shutdown.assert_called_once()
        monkeypatch.setattr(tp, "_provider_lock", rl)
        _reset_tracing_for_tests()
