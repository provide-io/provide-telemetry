# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Regression: early get_meter() before setup_metrics() must not block provider installation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from undef.telemetry.config import TelemetryConfig
from undef.telemetry.metrics import provider as prov_mod
from undef.telemetry.metrics.provider import _set_meter_for_test, get_meter, setup_metrics


@pytest.fixture(autouse=True)
def _clean_meters() -> None:
    _set_meter_for_test(None)


class TestEarlyGetMeterDoesNotBlockSetup:
    """Regression: calling get_meter() before setup_metrics() used to cache a
    noop meter under ``_meters["undef.telemetry"]``, causing setup_metrics() to
    short-circuit and never install the real provider."""

    def test_setup_metrics_installs_provider_after_early_get_meter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(prov_mod, "_HAS_OTEL_METRICS", True)

        # Simulate OTel API returning different meters before vs after provider setup
        pre_setup_meter = SimpleNamespace(tag="pre-setup")
        real_meter = SimpleNamespace(tag="real")
        _early_sentinel = object()

        def _fake_get_meter(name: str) -> object:
            if prov_mod._meter_provider is not None and prov_mod._meter_provider is not _early_sentinel:
                return real_meter
            return pre_setup_meter

        fake_otel = SimpleNamespace(
            get_meter=_fake_get_meter,
            set_meter_provider=Mock(),
        )
        monkeypatch.setattr(prov_mod, "_load_otel_metrics_api", lambda: fake_otel)

        # 1) Early get_meter() — before setup (gate requires non-None _meter_provider)
        prov_mod._meter_provider = _early_sentinel
        early = get_meter()
        assert early is pre_setup_meter
        prov_mod._meter_provider = None  # reset so setup_metrics can proceed

        # 2) Now run setup_metrics — must NOT short-circuit
        provider_cls = Mock(return_value="provider")
        resource_cls = SimpleNamespace(create=Mock(return_value="res"))
        reader_cls = Mock(return_value="reader")
        exporter_cls = Mock(return_value="exporter")
        monkeypatch.setattr(
            prov_mod,
            "_load_otel_metrics_components",
            lambda: (provider_cls, resource_cls, reader_cls, exporter_cls),
        )
        cfg = TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://metrics"})
        setup_metrics(cfg)

        # Provider must have been installed
        fake_otel.set_meter_provider.assert_called_once_with("provider")
        assert prov_mod._meter_provider == "provider"

        # 3) Post-setup get_meter() must return the real meter
        post = get_meter()
        assert post is real_meter

    def test_setup_metrics_clears_stale_custom_meters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Custom-named meters cached before setup must also be invalidated."""
        monkeypatch.setattr(prov_mod, "_HAS_OTEL_METRICS", True)

        real_meter = SimpleNamespace(tag="real")
        fake_otel = SimpleNamespace(
            get_meter=lambda name: real_meter,
            set_meter_provider=Mock(),
        )
        monkeypatch.setattr(prov_mod, "_load_otel_metrics_api", lambda: fake_otel)

        # Cache a custom-named meter before setup (gate requires non-None _meter_provider)
        _early_sentinel = object()
        prov_mod._meter_provider = _early_sentinel
        stale = get_meter("custom.service")
        assert stale is real_meter  # same object for simplicity
        assert "custom.service" in prov_mod._meters
        prov_mod._meter_provider = None  # reset so setup_metrics can proceed

        # Run setup
        provider_cls = Mock(return_value="provider")
        resource_cls = SimpleNamespace(create=Mock(return_value="res"))
        monkeypatch.setattr(
            prov_mod,
            "_load_otel_metrics_components",
            lambda: (provider_cls, resource_cls, Mock(), Mock()),
        )
        setup_metrics(TelemetryConfig.from_env({}))

        # Stale custom meter must have been cleared
        assert "custom.service" not in prov_mod._meters
        # Only the canonical meter should exist
        assert "undef.telemetry" in prov_mod._meters
