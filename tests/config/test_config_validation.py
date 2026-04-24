# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for endpoint-shadowing warnings and duration upper-bound validation."""

from __future__ import annotations

import warnings

import pytest

from provide.telemetry._config_validation import (
    MAX_DURATION_SECONDS,
    parse_duration_float,
    warn_on_endpoint_shadowing,
)
from provide.telemetry.config import TelemetryConfig
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
