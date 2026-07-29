# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""_has_effective_meter_provider — "is a provider in play", not "did we install one".

get_meter() already resolves a meter provider a host application installed on
the OTel global, so measurements are recorded through it; runtime status must
not report that signal as running in fallback.

No OTel extra required: the metrics API is monkeypatched throughout, which also
keeps these tests inside the mutation gate's non-otel selection.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from provide.telemetry.metrics import provider as mpmod
from provide.telemetry.runtime import get_runtime_status


class _ExternalProvider:
    """Shaped like an SDK provider: carries the force_flush/shutdown pair."""

    def force_flush(self, *_a: object, **_k: object) -> None: ...

    def shutdown(self, *_a: object, **_k: object) -> None: ...


class _ProxyMeterProvider:
    pass


def _install_meter_global(monkeypatch: pytest.MonkeyPatch, provider: object) -> None:
    """Put ``provider`` on the meter global with no setup_metrics() history of our own."""
    monkeypatch.setattr(mpmod, "_meter_provider", None)
    monkeypatch.setattr(mpmod, "_meter_global_set", False)
    monkeypatch.setattr(mpmod, "_load_otel_metrics_api", lambda: SimpleNamespace(get_meter_provider=lambda: provider))


class TestEffectiveMeterProviderProbe:
    def test_true_for_our_own_provider_without_consulting_the_global(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Our own provider ref answers on its own — no OTel API resolution required."""
        monkeypatch.setattr(mpmod, "_meter_provider", object())
        monkeypatch.setattr(mpmod, "_load_otel_metrics_api", lambda: None)
        assert mpmod._has_effective_meter_provider() is True

    def test_false_when_the_otel_api_is_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mpmod, "_meter_provider", None)
        monkeypatch.setattr(mpmod, "_load_otel_metrics_api", lambda: None)
        assert mpmod._has_effective_meter_provider() is False

    def test_true_for_a_provider_a_host_installed_itself(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_meter_global(monkeypatch, _ExternalProvider())
        # We installed nothing, so the install-scoped predicate still says no.
        assert mpmod._has_live_meter_provider() is False
        assert mpmod._has_effective_meter_provider() is True

    def test_false_when_the_global_is_the_api_placeholder(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_meter_global(monkeypatch, _ProxyMeterProvider())
        assert mpmod._has_effective_meter_provider() is False

    def test_false_after_our_own_provider_was_shut_down(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_meter_global(monkeypatch, _ExternalProvider())
        monkeypatch.setattr(mpmod, "_meter_global_set", True)
        assert mpmod._has_effective_meter_provider() is False


class TestRuntimeStatusReportsHostMeterProvider:
    def test_status_reports_a_host_meter_provider_as_installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_meter_global(monkeypatch, _ExternalProvider())
        status = get_runtime_status()
        assert status["providers"]["metrics"] is True  # type: ignore[index]
        assert status["fallback"]["metrics"] is False  # type: ignore[index]

    def test_status_reports_fallback_when_only_the_placeholder_is_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_meter_global(monkeypatch, _ProxyMeterProvider())
        status = get_runtime_status()
        assert status["providers"]["metrics"] is False  # type: ignore[index]
        assert status["fallback"]["metrics"] is True  # type: ignore[index]


def test_false_when_metrics_are_explicitly_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """A disabled signal has no provider in play, however live the global is.

    get_meter() checks _metrics_explicitly_disabled before anything else, so the
    probe must too — otherwise status claims an export path that get_meter()
    then refuses to hand back.
    """
    _install_meter_global(monkeypatch, _ExternalProvider())
    monkeypatch.setattr(mpmod, "_metrics_explicitly_disabled", True)
    assert mpmod._has_effective_meter_provider() is False
