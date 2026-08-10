# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for endpoint-shadowing warnings and duration upper-bound validation."""

from __future__ import annotations

import warnings
from collections.abc import Callable

import pytest

from provide.telemetry._config_validation import (
    MAX_DURATION_SECONDS,
    MAX_EXPORT_RETRIES,
    parse_duration_float,
    parse_env_retries,
    warn_on_endpoint_shadowing,
)
from provide.telemetry.config import ExporterPolicyConfig, TelemetryConfig
from provide.telemetry.exceptions import ConfigurationError

# ---------------------------------------------------------------------------
# parse_duration_float
# ---------------------------------------------------------------------------


class TestParseDurationFloat:
    def test_valid_value_parses(self) -> None:
        assert parse_duration_float("12.5", "x") == 12.5

    def test_zero_allowed(self) -> None:
        assert parse_duration_float("0", "x") == 0.0

    def test_max_boundary_allowed(self) -> None:
        assert parse_duration_float(str(MAX_DURATION_SECONDS), "x") == MAX_DURATION_SECONDS

    def test_above_max_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="<= 3600"):
            parse_duration_float(str(MAX_DURATION_SECONDS + 1), "x")

    def test_negative_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match=">= 0 seconds"):
            parse_duration_float("-1", "x")

    def test_garbage_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="invalid float"):
            parse_duration_float("not-a-number", "PROVIDE_TEST")


# ---------------------------------------------------------------------------
# Endpoint shadowing warning
# ---------------------------------------------------------------------------


class TestEndpointShadowingWarning:
    def test_no_warning_when_fallback_missing(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            warn_on_endpoint_shadowing({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://a"})
        assert caught == []

    def test_no_warning_when_specific_equals_fallback(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            warn_on_endpoint_shadowing(
                {
                    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318",
                    "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://collector:4318",
                }
            )
        assert caught == []

    def test_warning_when_logs_endpoint_shadows(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            warn_on_endpoint_shadowing(
                {
                    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://general:4318",
                    "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs:4318",
                }
            )
        assert len(caught) == 1
        assert issubclass(caught[0].category, UserWarning)
        message = str(caught[0].message)
        assert "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT" in message
        assert "OTEL_EXPORTER_OTLP_ENDPOINT" in message
        assert "http://logs:4318" in message

    def test_warning_for_traces_and_metrics_independently(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            warn_on_endpoint_shadowing(
                {
                    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://general:4318",
                    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://traces:4318",
                    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "http://metrics:4318",
                }
            )
        assert len(caught) == 2
        vars_mentioned = {str(w.message) for w in caught}
        joined = "\n".join(vars_mentioned)
        assert "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT" in joined
        assert "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT" in joined


# ---------------------------------------------------------------------------
# End-to-end: from_env wires shadowing + duration validation
# ---------------------------------------------------------------------------


class TestFromEnvIntegration:
    def test_from_env_emits_shadowing_warning(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            TelemetryConfig.from_env(
                {
                    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://general:4318",
                    "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs:4318",
                }
            )
        shadow_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
        assert any("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT" in str(w.message) for w in shadow_warnings)

    def test_from_env_rejects_oversize_timeout(self) -> None:
        with pytest.raises(ConfigurationError, match="<= 3600"):
            TelemetryConfig.from_env({"PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS": str(MAX_DURATION_SECONDS + 1)})

    def test_from_env_rejects_oversize_backoff(self) -> None:
        with pytest.raises(ConfigurationError, match="<= 3600"):
            TelemetryConfig.from_env({"PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS": str(MAX_DURATION_SECONDS + 10)})

    def test_from_env_rejects_negative_backoff(self) -> None:
        with pytest.raises(ConfigurationError, match=">= 0 seconds"):
            TelemetryConfig.from_env({"PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS": "-0.5"})

    def test_from_env_accepts_boundary_timeout(self) -> None:
        cfg = TelemetryConfig.from_env({"PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS": str(MAX_DURATION_SECONDS)})
        assert cfg.exporter.logs_timeout_seconds == MAX_DURATION_SECONDS


# ---------------------------------------------------------------------------
# exporter retries ceiling
# ---------------------------------------------------------------------------


class TestExportRetriesCeiling:
    """PROVIDE_EXPORTER_*_RETRIES shares TypeScript's ceiling (100 retries).

    An env shared across a polyglot deployment must fail the same way in every
    language — TypeScript already rejects a value above MAX_EXPORT_ATTEMPTS - 1,
    so Python must too, with the env var named in the error.
    """

    def test_ceiling_is_the_typescript_parity_value(self) -> None:
        assert MAX_EXPORT_RETRIES == 100

    def test_boundary_value_parses(self) -> None:
        assert parse_env_retries(str(MAX_EXPORT_RETRIES), "x") == MAX_EXPORT_RETRIES

    def test_above_ceiling_rejected_with_the_env_var_named(self) -> None:
        with pytest.raises(ConfigurationError, match="PROVIDE_TEST must be at most 100, got 101"):
            parse_env_retries(str(MAX_EXPORT_RETRIES + 1), "PROVIDE_TEST")

    def test_garbage_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="invalid integer for PROVIDE_TEST"):
            parse_env_retries("not-a-number", "PROVIDE_TEST")

    @pytest.mark.parametrize(
        "var",
        [
            "PROVIDE_EXPORTER_LOGS_RETRIES",
            "PROVIDE_EXPORTER_TRACES_RETRIES",
            "PROVIDE_EXPORTER_METRICS_RETRIES",
        ],
    )
    def test_from_env_rejects_each_signal_above_the_ceiling(self, var: str) -> None:
        with pytest.raises(ConfigurationError, match=f"{var} must be at most 100, got 150"):
            TelemetryConfig.from_env({var: "150"})

    def test_from_env_accepts_the_boundary(self) -> None:
        cfg = TelemetryConfig.from_env({"PROVIDE_EXPORTER_LOGS_RETRIES": str(MAX_EXPORT_RETRIES)})
        assert cfg.exporter.logs_retries == MAX_EXPORT_RETRIES

    @pytest.mark.parametrize(
        ("field", "make"),
        [
            ("logs_retries", lambda n: ExporterPolicyConfig(logs_retries=n)),
            ("traces_retries", lambda n: ExporterPolicyConfig(traces_retries=n)),
            ("metrics_retries", lambda n: ExporterPolicyConfig(metrics_retries=n)),
        ],
    )
    def test_explicit_config_is_held_to_the_same_ceiling(
        self, field: str, make: Callable[[int], ExporterPolicyConfig]
    ) -> None:
        """update_runtime_config takes ExporterPolicyConfig directly — the env
        parser never sees it, so the dataclass must enforce the ceiling itself."""
        assert make(MAX_EXPORT_RETRIES).__class__ is ExporterPolicyConfig
        with pytest.raises(ConfigurationError, match=f"{field} must be at most 100, got 101"):
            make(MAX_EXPORT_RETRIES + 1)


# ---------------------------------------------------------------------------
# ExporterPolicyConfig backoff/timeout floats: finite and non-negative
# ---------------------------------------------------------------------------


class TestExporterFloatValidation:
    """NaN/inf/negative backoff and timeout floats are rejected at construction.

    NaN otherwise slips through every range check — ``max(0.0, nan)`` is 0.0,
    which silently disables the export deadline, and NaN backoff comparisons
    drop the retry loop's sleep. Go, TypeScript and Rust reject the same
    values, so a shared config fails the same way in every language.
    """

    def test_nan_timeout_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="logs_timeout_seconds must be finite, got nan"):
            ExporterPolicyConfig(logs_timeout_seconds=float("nan"))

    def test_inf_backoff_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="traces_backoff_seconds must be finite, got inf"):
            ExporterPolicyConfig(traces_backoff_seconds=float("inf"))

    def test_negative_inf_timeout_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="metrics_timeout_seconds must be finite, got -inf"):
            ExporterPolicyConfig(metrics_timeout_seconds=float("-inf"))

    def test_negative_backoff_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match=r"logs_backoff_seconds must be >= 0, got -5\.0"):
            ExporterPolicyConfig(logs_backoff_seconds=-5.0)

    def test_negative_timeout_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match=r"traces_timeout_seconds must be >= 0, got -0\.1"):
            ExporterPolicyConfig(traces_timeout_seconds=-0.1)

    def test_zero_boundary_accepted(self) -> None:
        cfg = ExporterPolicyConfig(logs_timeout_seconds=0.0, metrics_backoff_seconds=0.0)
        assert cfg.logs_timeout_seconds == 0.0
        assert cfg.metrics_backoff_seconds == 0.0

    def test_nan_from_env_is_rejected_by_the_dataclass(self) -> None:
        """parse_duration_float's range checks are all False for NaN, so the
        dataclass __post_init__ is the gate that catches an env ``nan``."""
        with pytest.raises(ConfigurationError, match="logs_timeout_seconds must be finite"):
            TelemetryConfig.from_env({"PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS": "nan"})

    @pytest.mark.parametrize(
        ("field", "make"),
        [
            ("logs_backoff_seconds", lambda v: ExporterPolicyConfig(logs_backoff_seconds=v)),
            ("traces_backoff_seconds", lambda v: ExporterPolicyConfig(traces_backoff_seconds=v)),
            ("metrics_backoff_seconds", lambda v: ExporterPolicyConfig(metrics_backoff_seconds=v)),
            ("logs_timeout_seconds", lambda v: ExporterPolicyConfig(logs_timeout_seconds=v)),
            ("traces_timeout_seconds", lambda v: ExporterPolicyConfig(traces_timeout_seconds=v)),
            ("metrics_timeout_seconds", lambda v: ExporterPolicyConfig(metrics_timeout_seconds=v)),
        ],
    )
    def test_every_float_field_is_validated(self, field: str, make: Callable[[float], ExporterPolicyConfig]) -> None:
        with pytest.raises(ConfigurationError, match=f"{field} must be finite"):
            make(float("nan"))
