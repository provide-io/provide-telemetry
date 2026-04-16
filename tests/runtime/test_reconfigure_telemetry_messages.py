# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests killing surviving mutants in reconfigure_telemetry error messages.

Covers:
  reconfigure_telemetry: mutmut_11/14/15/17/25/26/28/29/30/31/32 (error message mutations)
"""

from __future__ import annotations

import pytest

from provide.telemetry import backpressure as backpressure_mod
from provide.telemetry import health as health_mod
from provide.telemetry import resilience as resilience_mod
from provide.telemetry import runtime as runtime_mod
from provide.telemetry import sampling as sampling_mod
from provide.telemetry.config import TelemetryConfig


@pytest.fixture(autouse=True)
def _reset() -> None:
    health_mod.reset_health_for_tests()
    sampling_mod.reset_sampling_for_tests()
    backpressure_mod.reset_queues_for_tests()
    resilience_mod.reset_resilience_for_tests()
    runtime_mod.reset_runtime_for_tests()


class TestReconfigureTelemetryErrorMessages:
    """Kill mutmut_11/14/15/17/25/26/28/29/30/31/32: error message mutations."""

    @pytest.fixture()
    def _stub_all_providers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from provide.telemetry.logger import core as logger_core
        from provide.telemetry.metrics import provider as metrics_provider
        from provide.telemetry.tracing import provider as tracing_provider

        monkeypatch.setattr(logger_core, "_has_otel_log_provider", lambda: True)
        monkeypatch.setattr(tracing_provider, "_has_tracing_provider", lambda: True)
        monkeypatch.setattr(metrics_provider, "_has_meter_provider", lambda: False)

    def test_provider_change_error_contains_opentelemetry(
        self, monkeypatch: pytest.MonkeyPatch, _stub_all_providers: None
    ) -> None:
        """Error for provider-changing reconfigure must contain 'OpenTelemetry'.

        Kills mutmut_11 (prefix "XX...XX").
        """
        runtime_mod.apply_runtime_config(TelemetryConfig(service_name="old-svc"))
        with pytest.raises(RuntimeError) as exc_info:
            runtime_mod.reconfigure_telemetry(TelemetryConfig(service_name="new-svc"))
        msg = str(exc_info.value)
        assert "OpenTelemetry" in msg
        # mutmut_11: "XX" prefix on "provider-changing..." — content still present as substring
        assert "XXprovider-changing" not in msg, f"Must not start segment with 'XX': {msg!r}"

    def test_provider_change_error_contains_reconfigure_telemetry(
        self, monkeypatch: pytest.MonkeyPatch, _stub_all_providers: None
    ) -> None:
        """Error must contain 'reconfigure_telemetry()'.

        Kills mutmut_14 (prefix change), mutmut_15 (case change).
        """
        runtime_mod.apply_runtime_config(TelemetryConfig(service_name="svc-a"))
        with pytest.raises(RuntimeError) as exc_info:
            runtime_mod.reconfigure_telemetry(TelemetryConfig(service_name="svc-b"))
        msg = str(exc_info.value)
        assert "reconfigure_telemetry()" in msg
        assert "Use reconfigure_telemetry()" in msg
        # mutmut_14: "XX" prefix on "Use reconfigure_telemetry()..." — substring still matches
        assert "XXUse reconfigure_telemetry" not in msg, f"Must not start segment with 'XX': {msg!r}"

    def test_provider_change_error_contains_setup_telemetry(
        self, monkeypatch: pytest.MonkeyPatch, _stub_all_providers: None
    ) -> None:
        """Error must contain 'setup_telemetry()'.

        Kills mutmut_17 (suffix "XX...XX").
        """
        runtime_mod.apply_runtime_config(TelemetryConfig(service_name="svc-a"))
        with pytest.raises(RuntimeError) as exc_info:
            runtime_mod.reconfigure_telemetry(TelemetryConfig(service_name="svc-b"))
        msg = str(exc_info.value)
        assert "setup_telemetry()" in msg
        # mutmut_17: "XX" prefix on "setup_telemetry()..." — substring still matches
        assert "XXsetup_telemetry" not in msg, f"Must not start segment with 'XX': {msg!r}"

    def _setup_log_provider_change(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[TelemetryConfig, TelemetryConfig]:
        """Helper: set up configs that trigger the log-provider change error path."""
        from provide.telemetry.logger import core as logger_core
        from provide.telemetry.metrics import provider as metrics_provider
        from provide.telemetry.tracing import provider as tracing_provider

        runtime_mod.apply_runtime_config(
            TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs"})
        )
        monkeypatch.setattr(logger_core, "_has_otel_log_provider", lambda: True)
        monkeypatch.setattr(tracing_provider, "_has_tracing_provider", lambda: False)
        monkeypatch.setattr(metrics_provider, "_has_meter_provider", lambda: False)
        cfg_a = TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs"})
        cfg_b = TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://other-logs"})
        return cfg_a, cfg_b

    def test_logging_provider_error_contains_opentelemetry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Log-provider error must contain 'OpenTelemetry'.

        Kills mutmut_25 (prefix "XX...XX"), mutmut_26 (lowercase).
        """
        _, cfg_b = self._setup_log_provider_change(monkeypatch)
        with pytest.raises(RuntimeError) as exc_info:
            runtime_mod.reconfigure_telemetry(cfg_b)
        msg = str(exc_info.value)
        assert "OpenTelemetry" in msg, f"Expected 'OpenTelemetry' in: {msg!r}"
        assert msg.count("OpenTelemetry") > 0
        # mutmut_25: "XX" prefix on "provider-changing logging..." — OpenTelemetry still present
        assert "XXprovider-changing logging" not in msg, f"Must not start segment with 'XX': {msg!r}"

    def test_logging_provider_error_contains_endpoint_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Log-provider error must mention endpoint/headers/timeout change.

        Kills mutmut_28 (prefix "XX...XX"), mutmut_29 (case change).
        """
        _, cfg_b = self._setup_log_provider_change(monkeypatch)
        with pytest.raises(RuntimeError) as exc_info:
            runtime_mod.reconfigure_telemetry(cfg_b)
        msg = str(exc_info.value)
        assert "endpoint" in msg.lower(), f"Expected 'endpoint' in: {msg!r}"
        assert "are installed" in msg, f"Expected 'are installed' in: {msg!r}"
        assert "ARE INSTALLED" not in msg
        # mutmut_28: "XX" prefix on "are installed..." — "are installed" still a substring
        assert "XXare installed" not in msg, f"Must not start segment with 'XX': {msg!r}"
        # mutmut_29: lowercase "use" → "use reconfigure_telemetry()" instead of "Use..."
        assert "Use reconfigure_telemetry()" in msg, f"'Use' must be capitalized: {msg!r}"

    def test_logging_provider_error_contains_setup_telemetry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Log-provider error must contain 'setup_telemetry()'.

        Kills mutmut_30 (suffix "XX...XX" around final sentence),
        mutmut_31 (prefix "XX...XX"), mutmut_32 (uppercase).
        """
        _, cfg_b = self._setup_log_provider_change(monkeypatch)
        with pytest.raises(RuntimeError) as exc_info:
            runtime_mod.reconfigure_telemetry(cfg_b)
        msg = str(exc_info.value)
        assert "setup_telemetry()" in msg, f"Expected 'setup_telemetry()' in: {msg!r}"
        assert "provider replacement" in msg, f"Expected 'provider replacement' in: {msg!r}"
        assert "PROVIDER REPLACEMENT" not in msg
        assert "SETUP_TELEMETRY()" not in msg
        # mutmut_30: wraps final sentence in "XX...XX" — message must end cleanly with period
        assert msg.rstrip().endswith("the new config."), (
            f"Error message must end with 'the new config.' (no XX suffix), got: {msg!r}"
        )
        assert "XXsetup_telemetry" not in msg, f"Must not have 'XX' prefix on setup_telemetry: {msg!r}"
        # mutmut_31: "XX" prefix on "Restart..." — substring still matches
        assert "XXRestart" not in msg, f"Must not start segment with 'XX': {msg!r}"
