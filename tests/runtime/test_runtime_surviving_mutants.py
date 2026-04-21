# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests killing surviving mutants in runtime.py.

Covers:
  _overrides_from_config: logging and event_schema field extraction (mutmut_8/9/17/18)
  _logging_provider_config_changed: otlp_headers and logs_timeout_seconds (mutmut_1/4/5)
  update_runtime_config: logging_changed sentinel, condition logic, configure_logging args (many)
  reconfigure_telemetry: error message content (mutmut_11/14/15/17/25/26/28/29/30/31/32)
"""

from __future__ import annotations

import pytest

from provide.telemetry import backpressure as backpressure_mod
from provide.telemetry import health as health_mod
from provide.telemetry import resilience as resilience_mod
from provide.telemetry import runtime as runtime_mod
from provide.telemetry import sampling as sampling_mod
from provide.telemetry.config import (
    ExporterPolicyConfig,
    LoggingConfig,
    RuntimeOverrides,
    SchemaConfig,
    TelemetryConfig,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    health_mod.reset_health_for_tests()
    sampling_mod.reset_sampling_for_tests()
    backpressure_mod.reset_queues_for_tests()
    resilience_mod.reset_resilience_for_tests()
    runtime_mod.reset_runtime_for_tests()


# ── _overrides_from_config: logging and event_schema fields ──────────────────


class TestOverridesFromConfigLoggingAndEventSchema:
    """Kill mutmut_8 (logging=None), mutmut_9 (event_schema=None),
    mutmut_17 (logging omitted), mutmut_18 (event_schema omitted)."""

    def test_logging_field_preserved(self) -> None:
        """logging must be extracted from config (not set to None or omitted)."""
        cfg = TelemetryConfig(
            logging=LoggingConfig(
                level="DEBUG",
                fmt="json",
                include_timestamp=False,
                include_caller=True,
                sanitize=False,
            )
        )
        overrides = runtime_mod._overrides_from_config(cfg)
        assert overrides.logging is not None
        assert overrides.logging is cfg.logging
        assert overrides.logging.level == "DEBUG"

    def test_event_schema_field_preserved(self) -> None:
        """event_schema must be extracted from config (not set to None or omitted)."""
        cfg = TelemetryConfig(
            event_schema=SchemaConfig(
                strict_event_name=True,
                required_keys=("request_id", "user_id"),
            )
        )
        overrides = runtime_mod._overrides_from_config(cfg)
        assert overrides.event_schema is not None
        assert overrides.event_schema is cfg.event_schema
        assert overrides.event_schema.strict_event_name is True
        assert "request_id" in overrides.event_schema.required_keys

    def test_logging_and_event_schema_both_present(self) -> None:
        """Both logging and event_schema must be present in the overrides."""
        cfg = TelemetryConfig(
            logging=LoggingConfig(level="WARNING"),
            event_schema=SchemaConfig(strict_event_name=False),
        )
        overrides = runtime_mod._overrides_from_config(cfg)
        assert overrides.logging is not None
        assert overrides.event_schema is not None

    def test_logging_level_not_default_survives_round_trip(self) -> None:
        """Non-default logging level must survive through _overrides_from_config."""
        cfg = TelemetryConfig(logging=LoggingConfig(level="ERROR"))
        overrides = runtime_mod._overrides_from_config(cfg)
        assert overrides.logging is not None
        assert overrides.logging.level == "ERROR"

    def test_event_schema_required_keys_not_default_survives_round_trip(self) -> None:
        """Non-default required_keys must survive through _overrides_from_config."""
        cfg = TelemetryConfig(event_schema=SchemaConfig(required_keys=("service", "env", "version")))
        overrides = runtime_mod._overrides_from_config(cfg)
        assert overrides.event_schema is not None
        assert "service" in overrides.event_schema.required_keys
        assert "env" in overrides.event_schema.required_keys


# ── _logging_provider_config_changed ─────────────────────────────────────────


class TestLoggingProviderConfigChanged:
    """Kill mutmut_1 (otlp_headers and logs_timeout precedence),
    mutmut_4 (headers == instead of !=), mutmut_5 (timeout == instead of !=)."""

    def _make_cfg(
        self,
        endpoint: str = "http://logs",
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
    ) -> TelemetryConfig:
        return TelemetryConfig.from_env(
            {
                "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": endpoint,
            }
        )

    def test_no_change_returns_false(self) -> None:
        """Same endpoint/headers/timeout → False (unchanged)."""
        cfg = TelemetryConfig()
        assert runtime_mod._logging_provider_config_changed(cfg, cfg) is False

    def test_endpoint_change_returns_true(self) -> None:
        """Different otlp_endpoint → True."""
        a = TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://a"})
        b = TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://b"})
        assert runtime_mod._logging_provider_config_changed(a, b) is True

    def test_headers_change_returns_true(self) -> None:
        """Different otlp_headers → True.

        Kills mutmut_4: headers == target.logging.otlp_headers (inverted check
        would return True when headers are SAME, False when different).
        Kills mutmut_1: operator precedence change (and vs or between headers/timeout).
        """
        # Build configs with same endpoint but different headers
        same_endpoint = "http://logs:4318"
        a = TelemetryConfig.from_env(
            {
                "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": same_endpoint,
                "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "x-auth=token1",
            }
        )
        b = TelemetryConfig.from_env(
            {
                "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": same_endpoint,
                "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "x-auth=token2",
            }
        )
        assert runtime_mod._logging_provider_config_changed(a, b) is True

    def test_headers_same_returns_false(self) -> None:
        """Same headers → False (kills mutmut_4 inverted check)."""
        same_endpoint = "http://logs:4318"
        a = TelemetryConfig.from_env(
            {
                "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": same_endpoint,
                "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "x-auth=same",
            }
        )
        b = TelemetryConfig.from_env(
            {
                "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": same_endpoint,
                "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "x-auth=same",
            }
        )
        assert runtime_mod._logging_provider_config_changed(a, b) is False

    def test_timeout_change_returns_true(self) -> None:
        """Different logs_timeout_seconds → True.

        Kills mutmut_5: timeout == target.exporter.logs_timeout_seconds (inverted
        check would return True when timeouts are SAME, False when different).
        """
        a = TelemetryConfig(exporter=ExporterPolicyConfig(logs_timeout_seconds=10.0))
        b = TelemetryConfig(exporter=ExporterPolicyConfig(logs_timeout_seconds=20.0))
        assert runtime_mod._logging_provider_config_changed(a, b) is True

    def test_timeout_same_returns_false(self) -> None:
        """Same timeout → False (kills mutmut_5 inverted check)."""
        a = TelemetryConfig(exporter=ExporterPolicyConfig(logs_timeout_seconds=30.0))
        b = TelemetryConfig(exporter=ExporterPolicyConfig(logs_timeout_seconds=30.0))
        assert runtime_mod._logging_provider_config_changed(a, b) is False

    def test_only_timeout_changed_returns_true(self) -> None:
        """Timeout-only change must still trigger True (kills mutmut_1 and-precedence).

        mutmut_1 changes:
          (headers != target.headers) or (timeout != target.timeout)
        into:
          (headers != target.headers) and (timeout != target.timeout)
        Then a timeout-only change (headers same) would return False.
        """
        base_endpoint = "http://logs:4318"
        a = TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": base_endpoint})
        a.exporter.logs_timeout_seconds = 10.0
        b = TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": base_endpoint})
        b.exporter.logs_timeout_seconds = 99.0
        # Both have the same endpoint and default headers — only timeout differs
        assert a.logging.otlp_headers == b.logging.otlp_headers  # pre-condition
        assert runtime_mod._logging_provider_config_changed(a, b) is True

    def test_only_headers_changed_returns_true(self) -> None:
        """Headers-only change must trigger True (kills mutmut_1 and-precedence)."""
        same_endpoint = "http://logs:4318"
        a = TelemetryConfig.from_env(
            {
                "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": same_endpoint,
                "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "k=v1",
            }
        )
        b = TelemetryConfig.from_env(
            {
                "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": same_endpoint,
                "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "k=v2",
            }
        )
        # Same endpoint, same timeout, different headers only
        assert a.exporter.logs_timeout_seconds == b.exporter.logs_timeout_seconds  # pre-condition
        assert runtime_mod._logging_provider_config_changed(a, b) is True


# ── update_runtime_config: logging_changed flag logic ───────────────────────


class TestUpdateRuntimeConfigLoggingChangedFlag:
    """Kill mutmut_1 (logging_changed=None), mutmut_2 (logging_changed=True init),
    mutmut_5 (and→or), mutmut_6 (is not None→is None), mutmut_7 (!=→==),
    mutmut_8 (True→None), mutmut_9 (True→False)."""

    def test_logging_unchanged_does_not_trigger_reconfigure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When logging config is unchanged, configure_logging must NOT be called.

        Kills mutmut_2 (logging_changed=True at init) and mutmut_5 (and→or).
        With mutmut_2, configure_logging would be called even when nothing changed.
        With mutmut_5 (or), the condition fires whenever overrides.logging is not None,
        even if the value is identical to the existing config.
        """
        import importlib

        logger_core = importlib.import_module("provide.telemetry.logger.core")
        configure_calls: list[object] = []
        monkeypatch.setattr(
            logger_core, "configure_logging", lambda cfg, force=False: configure_calls.append((cfg, force))
        )
        base = TelemetryConfig.from_env()
        runtime_mod.apply_runtime_config(base)
        # Override with IDENTICAL logging config — must not trigger reconfigure
        runtime_mod.update_runtime_config(RuntimeOverrides(logging=base.logging))
        assert configure_calls == [], "configure_logging was called even though logging config did not change"

    def test_logging_changed_triggers_reconfigure_with_force_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When logging config changes, configure_logging(merged, force=True) must be called.

        Kills mutmut_8 (True→None), mutmut_9 (True→False), mutmut_31 (force=None),
        mutmut_33 (force omitted), mutmut_34 (force=False), mutmut_30 (merged→None).
        """
        import importlib

        logger_core = importlib.import_module("provide.telemetry.logger.core")
        calls: list[tuple[object, bool]] = []
        monkeypatch.setattr(logger_core, "configure_logging", lambda cfg, force=False: calls.append((cfg, force)))
        base = TelemetryConfig.from_env()
        runtime_mod.apply_runtime_config(base)
        new_logging = LoggingConfig(
            level="DEBUG",
            fmt=base.logging.fmt,
            include_timestamp=base.logging.include_timestamp,
            include_caller=base.logging.include_caller,
            sanitize=base.logging.sanitize,
        )
        runtime_mod.update_runtime_config(RuntimeOverrides(logging=new_logging))
        assert len(calls) == 1, f"Expected 1 call to configure_logging, got {len(calls)}"
        cfg_arg, force_arg = calls[0]
        assert force_arg is True, f"Expected force=True but got force={force_arg!r}"
        # Verify the config passed is the merged one (not None)
        assert cfg_arg is not None, "configure_logging received None config"
        assert isinstance(cfg_arg, TelemetryConfig)
        # The merged config should have the new logging level
        assert cfg_arg.logging.level == "DEBUG"

    def test_logging_none_override_does_not_trigger_reconfigure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When overrides.logging is None, configure_logging must NOT be called.

        Kills mutmut_6 (is None instead of is not None).
        """
        import importlib

        logger_core = importlib.import_module("provide.telemetry.logger.core")
        configure_calls: list[object] = []
        monkeypatch.setattr(
            logger_core, "configure_logging", lambda cfg, force=False: configure_calls.append((cfg, force))
        )
        runtime_mod.apply_runtime_config(TelemetryConfig.from_env())
        # No logging override — must not trigger reconfigure
        runtime_mod.update_runtime_config(RuntimeOverrides(strict_schema=True))
        assert configure_calls == []

    def test_logging_changed_flag_with_same_value_not_triggered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When overrides.logging is not None but EQUALS base.logging, no reconfigure.

        Kills mutmut_7 (!=→==): with ==, the flag would be set when values ARE equal
        (opposite of desired behavior).
        """
        import importlib

        logger_core = importlib.import_module("provide.telemetry.logger.core")
        calls: list[object] = []
        monkeypatch.setattr(logger_core, "configure_logging", lambda cfg, force=False: calls.append((cfg, force)))
        base = TelemetryConfig.from_env()
        runtime_mod.apply_runtime_config(base)
        # Pass the EXACT SAME logging config object
        runtime_mod.update_runtime_config(RuntimeOverrides(logging=base.logging))
        assert calls == [], "configure_logging should not be called when logging config is unchanged"


# ── update_runtime_config: error message content ──────────────────────────────


class TestUpdateRuntimeConfigErrorMessages:
    """Kill mutmut_20/21/23/24/25/26/27: error message string mutations."""

    def test_error_message_contains_opentelemetry_capitalized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Error must contain "OpenTelemetry" (capital O and T).

        Kills mutmut_21 ("opentelemetry" lowercase).
        """
        from provide.telemetry.logger import core as logger_core

        runtime_mod.apply_runtime_config(TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs"}))
        monkeypatch.setattr(logger_core, "_has_real_otel_log_provider", lambda: True)
        with pytest.raises(RuntimeError) as exc_info:
            runtime_mod.update_runtime_config(
                RuntimeOverrides(
                    logging=LoggingConfig(
                        level="INFO",
                        fmt="json",
                        include_timestamp=True,
                        include_caller=False,
                        sanitize=True,
                        otlp_endpoint="http://other-logs",
                    )
                )
            )
        msg = str(exc_info.value)
        assert "OpenTelemetry" in msg, f"Expected 'OpenTelemetry' in error, got: {msg!r}"
        assert "opentelemetry" not in msg.replace("OpenTelemetry", ""), "Must not be lowercase"
        # mutmut_20: prefix "XX" prepended to "provider-changing..."
        assert "XXprovider-changing" not in msg, f"Message must not start segment with 'XX': {msg!r}"

    def test_error_message_contains_reconfigure_telemetry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Error must contain 'reconfigure_telemetry()' (exact case).

        Kills mutmut_23/24/25 (case/prefix changes).
        """
        from provide.telemetry.logger import core as logger_core

        runtime_mod.apply_runtime_config(TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs"}))
        monkeypatch.setattr(logger_core, "_has_real_otel_log_provider", lambda: True)
        with pytest.raises(RuntimeError) as exc_info:
            runtime_mod.update_runtime_config(
                RuntimeOverrides(
                    logging=LoggingConfig(
                        level="INFO",
                        fmt="json",
                        include_timestamp=True,
                        include_caller=False,
                        sanitize=True,
                        otlp_endpoint="http://other",
                    )
                )
            )
        msg = str(exc_info.value)
        assert "reconfigure_telemetry()" in msg, f"Expected 'reconfigure_telemetry()' in: {msg!r}"
        assert "Use reconfigure_telemetry()" in msg, f"Expected 'Use reconfigure_telemetry()' in: {msg!r}"
        # mutmut_23: prefix "XX" prepended to "are installed..."
        assert "XXare installed" not in msg, f"Message must not start segment with 'XX': {msg!r}"

    def test_error_message_contains_setup_telemetry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Error must contain 'setup_telemetry()'.

        Kills mutmut_26/27 (suffix changes).
        """
        from provide.telemetry.logger import core as logger_core

        runtime_mod.apply_runtime_config(TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs"}))
        monkeypatch.setattr(logger_core, "_has_real_otel_log_provider", lambda: True)
        with pytest.raises(RuntimeError) as exc_info:
            runtime_mod.update_runtime_config(
                RuntimeOverrides(
                    logging=LoggingConfig(
                        level="INFO",
                        fmt="json",
                        include_timestamp=True,
                        include_caller=False,
                        sanitize=True,
                        otlp_endpoint="http://other",
                    )
                )
            )
        msg = str(exc_info.value)
        assert "setup_telemetry()" in msg, f"Expected 'setup_telemetry()' in: {msg!r}"
        assert "process and call setup_telemetry()" in msg
        # mutmut_26: prefix "XX" prepended to "process and call..."
        assert "XXprocess" not in msg, f"Message must not start segment with 'XX': {msg!r}"
