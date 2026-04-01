# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Edge-case and boundary tests for config parsing and validation."""

from __future__ import annotations

import pytest

from provide.telemetry.config import (
    BackpressureConfig,
    ExporterPolicyConfig,
    LoggingConfig,
    SamplingConfig,
    SchemaConfig,
    TelemetryConfig,
    TracingConfig,
    _parse_bool,
    _parse_env_float,
    _parse_env_int,
    _parse_otlp_headers,
)

# ── _parse_bool edge cases ─────────────────────────────────────────────


class TestParseBoolEdgeCases:
    def test_whitespace_padded(self) -> None:
        assert _parse_bool("  true  ", False) is True
        assert _parse_bool("  1  ", False) is True
        assert _parse_bool("  on  ", False) is True

    def test_empty_string_returns_false(self) -> None:
        assert _parse_bool("", True) is False

    def test_whitespace_only_returns_false(self) -> None:
        assert _parse_bool("   ", True) is False

    def test_all_truthy_variants(self) -> None:
        for val in ("1", "true", "TRUE", "True", "yes", "YES", "on", "ON"):
            assert _parse_bool(val, False) is True, f"Expected True for {val!r}"

    def test_all_falsy_variants(self) -> None:
        for val in ("0", "false", "FALSE", "no", "off", "random", "nope"):
            assert _parse_bool(val, True) is False, f"Expected False for {val!r}"


# ── _parse_env_float edge cases ────────────────────────────────────────


class TestParseEnvFloatEdgeCases:
    def test_zero(self) -> None:
        assert _parse_env_float("0", "X") == 0.0
        assert _parse_env_float("0.0", "X") == 0.0

    def test_negative(self) -> None:
        assert _parse_env_float("-1.5", "X") == -1.5

    def test_scientific_notation(self) -> None:
        assert _parse_env_float("1e2", "X") == 100.0
        assert _parse_env_float("1.5e-3", "X") == 0.0015

    def test_inf_accepted_by_parser(self) -> None:
        assert _parse_env_float("inf", "X") == float("inf")
        assert _parse_env_float("-inf", "X") == float("-inf")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid float for X"):
            _parse_env_float("", "X")

    def test_field_name_in_error(self) -> None:
        with pytest.raises(ValueError, match="PROVIDE_TRACE_SAMPLE_RATE"):
            _parse_env_float("nope", "PROVIDE_TRACE_SAMPLE_RATE")


# ── _parse_env_int edge cases ──────────────────────────────────────────


class TestParseEnvIntEdgeCases:
    def test_zero(self) -> None:
        assert _parse_env_int("0", "X") == 0

    def test_negative(self) -> None:
        assert _parse_env_int("-1", "X") == -1
        assert _parse_env_int("-100", "X") == -100

    def test_leading_zeros(self) -> None:
        assert _parse_env_int("0042", "X") == 42

    def test_float_string_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid integer for X"):
            _parse_env_int("1.5", "X")

    def test_scientific_notation_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid integer for X"):
            _parse_env_int("1e2", "X")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid integer for X"):
            _parse_env_int("", "X")

    def test_field_name_in_error(self) -> None:
        with pytest.raises(ValueError, match="PROVIDE_BACKPRESSURE_LOGS_MAXSIZE"):
            _parse_env_int("abc", "PROVIDE_BACKPRESSURE_LOGS_MAXSIZE")


# ── _parse_otlp_headers edge cases ─────────────────────────────────────


class TestParseOtlpHeadersEdgeCases:
    def test_trailing_comma(self) -> None:
        assert _parse_otlp_headers("a=b,") == {"a": "b"}

    def test_empty_value(self) -> None:
        assert _parse_otlp_headers("a=") == {"a": ""}

    def test_empty_value_between_valid(self) -> None:
        assert _parse_otlp_headers("a=,b=c") == {"a": "", "b": "c"}

    def test_multiple_equals_in_value(self) -> None:
        assert _parse_otlp_headers("a=b=c=d") == {"a": "b=c=d"}

    def test_duplicate_keys_last_wins(self) -> None:
        assert _parse_otlp_headers("a=first,a=second") == {"a": "second"}

    def test_whitespace_in_key_and_value(self) -> None:
        # Key is stripped, value is stripped then URL-decoded
        assert _parse_otlp_headers("  key  =  value  ") == {"key": "value"}


# ── Validation boundary tests ──────────────────────────────────────────


class TestValidationBoundaries:
    def test_sampling_rate_near_boundaries(self) -> None:
        cfg = SamplingConfig(logs_rate=0.0000001, traces_rate=0.9999999, metrics_rate=0.5)
        assert cfg.logs_rate == pytest.approx(0.0000001)
        assert cfg.traces_rate == pytest.approx(0.9999999)

    def test_sampling_rate_negative_epsilon(self) -> None:
        with pytest.raises(ValueError, match="sampling rate"):
            SamplingConfig(logs_rate=-0.0000001)

    def test_sampling_rate_over_one_epsilon(self) -> None:
        with pytest.raises(ValueError, match="sampling rate"):
            SamplingConfig(traces_rate=1.0000001)

    def test_tracing_sample_rate_near_boundaries(self) -> None:
        assert TracingConfig(sample_rate=0.0000001).sample_rate == pytest.approx(0.0000001)
        assert TracingConfig(sample_rate=0.9999999).sample_rate == pytest.approx(0.9999999)

    def test_backpressure_large_value(self) -> None:
        cfg = BackpressureConfig(logs_maxsize=2**31)
        assert cfg.logs_maxsize == 2**31

    def test_backpressure_all_signals_negative(self) -> None:
        with pytest.raises(ValueError, match="queue maxsize"):
            BackpressureConfig(traces_maxsize=-1)
        with pytest.raises(ValueError, match="queue maxsize"):
            BackpressureConfig(metrics_maxsize=-1)

    def test_inf_sample_rate_rejected(self) -> None:
        """inf parses as float but fails rate validation."""
        with pytest.raises(ValueError, match="sample_rate must be between 0 and 1"):
            TelemetryConfig.from_env({"PROVIDE_TRACE_SAMPLE_RATE": "inf"})

    def test_negative_sample_rate_from_env(self) -> None:
        with pytest.raises(ValueError, match="sample_rate must be between 0 and 1"):
            TelemetryConfig.from_env({"PROVIDE_TRACE_SAMPLE_RATE": "-0.5"})


# ── Log level / format edge cases ──────────────────────────────────────


class TestLogLevelFormatEdgeCases:
    def test_mixed_case_level_normalized(self) -> None:
        assert LoggingConfig(level="DeBuG").level == "DEBUG"
        assert LoggingConfig(level="warning").level == "WARNING"

    def test_empty_level_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid log level"):
            LoggingConfig(level="")

    def test_format_case_sensitive(self) -> None:
        with pytest.raises(ValueError, match="invalid log format: Console"):
            LoggingConfig(fmt="Console")


# ── Required keys edge cases ───────────────────────────────────────────


class TestRequiredKeysEdgeCases:
    def test_empty_string_produces_empty_tuple(self) -> None:
        cfg = TelemetryConfig.from_env({"PROVIDE_TELEMETRY_REQUIRED_KEYS": ""})
        assert cfg.event_schema.required_keys == ()

    def test_whitespace_only_produces_empty_tuple(self) -> None:
        cfg = TelemetryConfig.from_env({"PROVIDE_TELEMETRY_REQUIRED_KEYS": "  ,  ,  "})
        assert cfg.event_schema.required_keys == ()

    def test_duplicate_keys_preserved(self) -> None:
        cfg = TelemetryConfig.from_env({"PROVIDE_TELEMETRY_REQUIRED_KEYS": "a,a,b"})
        assert cfg.event_schema.required_keys == ("a", "a", "b")

    def test_keys_with_special_chars(self) -> None:
        cfg = TelemetryConfig.from_env({"PROVIDE_TELEMETRY_REQUIRED_KEYS": "request-id,user.id"})
        assert cfg.event_schema.required_keys == ("request-id", "user.id")

    def test_schema_config_defaults(self) -> None:
        s = SchemaConfig()
        assert s.strict_event_name is False
        assert s.required_keys == ()


# ── OTLP endpoint priority ─────────────────────────────────────────────


class TestOtlpEndpointPriority:
    def test_specific_overrides_general(self) -> None:
        cfg = TelemetryConfig.from_env(
            {
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://general",
                "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs-specific",
            }
        )
        assert cfg.logging.otlp_endpoint == "http://logs-specific"
        assert cfg.tracing.otlp_endpoint == "http://general"
        assert cfg.metrics.otlp_endpoint == "http://general"

    def test_specific_headers_override_general(self) -> None:
        cfg = TelemetryConfig.from_env(
            {
                "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Basic%20general",
                "OTEL_EXPORTER_OTLP_TRACES_HEADERS": "Authorization=Basic%20traces",
            }
        )
        assert cfg.tracing.otlp_headers == {"Authorization": "Basic traces"}
        assert cfg.logging.otlp_headers == {"Authorization": "Basic general"}

    def test_no_endpoints_gives_none(self) -> None:
        cfg = TelemetryConfig.from_env({})
        assert cfg.logging.otlp_endpoint is None
        assert cfg.tracing.otlp_endpoint is None
        assert cfg.metrics.otlp_endpoint is None


# ── Cross-field interaction tests ──────────────────────────────────────


class TestCrossFieldInteractions:
    def test_all_sampling_rates_at_different_values(self) -> None:
        cfg = TelemetryConfig.from_env(
            {
                "PROVIDE_SAMPLING_LOGS_RATE": "0.0",
                "PROVIDE_SAMPLING_TRACES_RATE": "1.0",
                "PROVIDE_SAMPLING_METRICS_RATE": "0.5",
            }
        )
        assert cfg.sampling.logs_rate == 0.0
        assert cfg.sampling.traces_rate == 1.0
        assert cfg.sampling.metrics_rate == 0.5

    def test_all_backpressure_at_different_sizes(self) -> None:
        cfg = TelemetryConfig.from_env(
            {
                "PROVIDE_BACKPRESSURE_LOGS_MAXSIZE": "10",
                "PROVIDE_BACKPRESSURE_TRACES_MAXSIZE": "20",
                "PROVIDE_BACKPRESSURE_METRICS_MAXSIZE": "30",
            }
        )
        assert cfg.backpressure.logs_maxsize == 10
        assert cfg.backpressure.traces_maxsize == 20
        assert cfg.backpressure.metrics_maxsize == 30

    def test_exporter_policy_defaults(self) -> None:
        epc = ExporterPolicyConfig()
        assert epc.logs_retries == 0
        assert epc.logs_backoff_seconds == 0.0
        assert epc.logs_timeout_seconds == 10.0
        assert epc.logs_fail_open is True
        assert epc.logs_allow_blocking_in_event_loop is False

    def test_exporter_all_fail_closed_no_retries(self) -> None:
        cfg = TelemetryConfig.from_env(
            {
                "PROVIDE_EXPORTER_LOGS_FAIL_OPEN": "false",
                "PROVIDE_EXPORTER_TRACES_FAIL_OPEN": "false",
                "PROVIDE_EXPORTER_METRICS_FAIL_OPEN": "false",
                "PROVIDE_EXPORTER_LOGS_RETRIES": "0",
                "PROVIDE_EXPORTER_TRACES_RETRIES": "0",
                "PROVIDE_EXPORTER_METRICS_RETRIES": "0",
            }
        )
        assert cfg.exporter.logs_fail_open is False
        assert cfg.exporter.traces_fail_open is False
        assert cfg.exporter.metrics_fail_open is False

    def test_exporter_custom_timeouts(self) -> None:
        cfg = TelemetryConfig.from_env(
            {
                "PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS": "0.1",
                "PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS": "30.0",
                "PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS": "0.0",
            }
        )
        assert cfg.exporter.logs_timeout_seconds == pytest.approx(0.1)
        assert cfg.exporter.traces_timeout_seconds == 30.0
        assert cfg.exporter.metrics_timeout_seconds == 0.0

    def test_slo_all_enabled(self) -> None:
        cfg = TelemetryConfig.from_env(
            {
                "PROVIDE_SLO_ENABLE_RED_METRICS": "true",
                "PROVIDE_SLO_ENABLE_USE_METRICS": "true",
                "PROVIDE_SLO_INCLUDE_ERROR_TAXONOMY": "false",
            }
        )
        assert cfg.slo.enable_red_metrics is True
        assert cfg.slo.enable_use_metrics is True
        assert cfg.slo.include_error_taxonomy is False

    def test_from_env_with_none_uses_os_environ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROVIDE_TELEMETRY_SERVICE_NAME", "from-os")
        cfg = TelemetryConfig.from_env()
        assert cfg.service_name == "from-os"
