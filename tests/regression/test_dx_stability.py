# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Tests for DX and stability improvements.

Covers: exception hierarchy, __all__ exports, logging/warnings
on silent failures (metrics fallback, rollback, sampling clamping,
OTLP headers, OTel import debug logging).
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from undef.telemetry.backpressure import reset_queues_for_tests
from undef.telemetry.exceptions import ConfigurationError, TelemetryError
from undef.telemetry.health import reset_health_for_tests
from undef.telemetry.sampling import reset_sampling_for_tests


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    reset_sampling_for_tests()
    reset_queues_for_tests()
    reset_health_for_tests()


# ── Exception hierarchy ──────────────────────────────────────────────


class TestExceptionHierarchy:
    def test_telemetry_error_is_base(self) -> None:
        assert issubclass(TelemetryError, Exception)

    def test_configuration_error_is_telemetry_error(self) -> None:
        assert issubclass(ConfigurationError, TelemetryError)

    def test_configuration_error_is_value_error(self) -> None:
        assert issubclass(ConfigurationError, ValueError)

    def test_event_schema_error_is_telemetry_error(self) -> None:
        from undef.telemetry.schema.events import EventSchemaError

        assert issubclass(EventSchemaError, TelemetryError)

    def test_event_schema_error_is_value_error(self) -> None:
        from undef.telemetry.schema.events import EventSchemaError

        assert issubclass(EventSchemaError, ValueError)

    def test_config_errors_raise_configuration_error(self) -> None:
        from undef.telemetry.config import _parse_env_float

        with pytest.raises(ConfigurationError):
            _parse_env_float("not-a-number", "TEST_FIELD")

    def test_config_errors_still_caught_by_value_error(self) -> None:
        from undef.telemetry.config import _parse_env_int

        with pytest.raises(ValueError):
            _parse_env_int("not-an-int", "TEST_FIELD")

    def test_exported_from_top_level(self) -> None:
        import undef.telemetry

        assert hasattr(undef.telemetry, "TelemetryError")
        assert hasattr(undef.telemetry, "ConfigurationError")
        assert hasattr(undef.telemetry, "EventSchemaError")

    def test_in_top_level_all(self) -> None:
        import undef.telemetry

        assert "TelemetryError" in undef.telemetry.__all__
        assert "ConfigurationError" in undef.telemetry.__all__
        assert "EventSchemaError" in undef.telemetry.__all__


# ── __all__ exports ──────────────────────────────────────────────────


class TestModuleAll:
    @pytest.mark.parametrize(
        "module_path",
        [
            "undef.telemetry",
            "undef.telemetry.config",
            "undef.telemetry.sampling",
            "undef.telemetry.backpressure",
            "undef.telemetry.health",
            "undef.telemetry.pii",
            "undef.telemetry.propagation",
            "undef.telemetry.resilience",
            "undef.telemetry.runtime",
            "undef.telemetry.slo",
            "undef.telemetry.cardinality",
            "undef.telemetry.headers",
            "undef.telemetry.schema.events",
            "undef.telemetry._otel",
            "undef.telemetry.setup",
            "undef.telemetry.exceptions",
            "undef.telemetry.metrics",
            "undef.telemetry.metrics.api",
            "undef.telemetry.logger",
            "undef.telemetry.tracing",
        ],
    )
    def test_module_defines_all(self, module_path: str) -> None:
        import importlib

        mod = importlib.import_module(module_path)
        assert hasattr(mod, "__all__"), f"{module_path} missing __all__"
        assert isinstance(mod.__all__, list)
        assert len(mod.__all__) > 0

    @pytest.mark.parametrize(
        "module_path",
        [
            "undef.telemetry.config",
            "undef.telemetry.sampling",
            "undef.telemetry.backpressure",
            "undef.telemetry.health",
            "undef.telemetry.pii",
            "undef.telemetry.propagation",
            "undef.telemetry.resilience",
            "undef.telemetry.runtime",
            "undef.telemetry.slo",
            "undef.telemetry.cardinality",
            "undef.telemetry.headers",
            "undef.telemetry.schema.events",
            "undef.telemetry.exceptions",
        ],
    )
    def test_all_entries_exist(self, module_path: str) -> None:
        import importlib

        mod = importlib.import_module(module_path)
        for name in mod.__all__:
            assert hasattr(mod, name), f"{module_path}.__all__ has {name!r} but it doesn't exist"


# ── Lazy slo loading via __getattr__ ─────────────────────────────────


class TestLazySloLoading:
    def test_classify_error_accessible_via_top_level(self) -> None:
        import undef.telemetry

        fn = undef.telemetry.classify_error
        assert callable(fn)
        result = fn("ValueError", None)
        assert "error_type" in result

    def test_record_red_metrics_accessible_via_top_level(self) -> None:
        import undef.telemetry

        assert callable(undef.telemetry.record_red_metrics)

    def test_record_use_metrics_accessible_via_top_level(self) -> None:
        import undef.telemetry

        assert callable(undef.telemetry.record_use_metrics)

    def test_unknown_attr_raises_attribute_error(self) -> None:
        import undef.telemetry

        with pytest.raises(AttributeError, match="no_such_thing"):
            undef.telemetry.no_such_thing  # noqa: B018

    def test_all_entries_accessible(self) -> None:
        """Every name in __all__ must be resolvable (including lazy ones)."""
        import undef.telemetry

        for name in undef.telemetry.__all__:
            assert hasattr(undef.telemetry, name), f"__all__ has {name!r} but it's not accessible"


# ── Metric creation logging ─────────────────────────────────────────


class TestMetricCreationLogging:
    def test_counter_creation_failure_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        from undef.telemetry.metrics.api import counter

        broken_meter = MagicMock()
        broken_meter.create_counter.side_effect = TypeError("bad counter")

        with (
            patch("undef.telemetry.metrics.api.get_meter", return_value=broken_meter),
            caplog.at_level(logging.WARNING, logger="undef.telemetry.metrics.api"),
        ):
            c = counter("test.counter")

        assert c.name == "test.counter"
        assert c._otel_counter is None
        assert "failed to create OTel counter" in caplog.text

    def test_gauge_creation_failure_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        from undef.telemetry.metrics.api import gauge

        broken_meter = MagicMock()
        broken_meter.create_up_down_counter.side_effect = TypeError("bad gauge")

        with (
            patch("undef.telemetry.metrics.api.get_meter", return_value=broken_meter),
            caplog.at_level(logging.WARNING, logger="undef.telemetry.metrics.api"),
        ):
            g = gauge("test.gauge")

        assert g.name == "test.gauge"
        assert g._otel_gauge is None
        assert "failed to create OTel gauge" in caplog.text

    def test_histogram_creation_failure_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        from undef.telemetry.metrics.api import histogram

        broken_meter = MagicMock()
        broken_meter.create_histogram.side_effect = TypeError("bad histogram")

        with (
            patch("undef.telemetry.metrics.api.get_meter", return_value=broken_meter),
            caplog.at_level(logging.WARNING, logger="undef.telemetry.metrics.api"),
        ):
            h = histogram("test.histogram")

        assert h.name == "test.histogram"
        assert h._otel_histogram is None
        assert "failed to create OTel histogram" in caplog.text


# ── Setup rollback logging ──────────────────────────────────────────


class TestSetupRollbackLogging:
    def test_rollback_logs_suppressed_exceptions(self, caplog: pytest.LogCaptureFixture) -> None:
        from undef.telemetry.setup import _rollback

        with (
            patch("undef.telemetry.setup.shutdown_logging", side_effect=RuntimeError("teardown failed")),
            caplog.at_level(logging.WARNING, logger="undef.telemetry.setup"),
        ):
            _rollback(["configure_logging"])

        assert "rollback failed for configure_logging" in caplog.text

    def test_rollback_continues_after_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        from undef.telemetry.setup import _rollback

        call_order: list[str] = []

        def _fail_logging() -> None:
            call_order.append("logging")
            raise RuntimeError("logging teardown failed")

        def _ok_tracing() -> None:
            call_order.append("tracing")

        with (
            patch("undef.telemetry.setup.shutdown_logging", side_effect=_fail_logging),
            patch("undef.telemetry.setup.shutdown_tracing", side_effect=_ok_tracing),
            caplog.at_level(logging.WARNING, logger="undef.telemetry.setup"),
        ):
            _rollback(["setup_tracing", "configure_logging"])

        assert call_order == ["logging", "tracing"]


# ── Sampling rate clamping ───────────────────────────────────────────


class TestSamplingRateClampingWarning:
    def test_rate_above_one_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        from undef.telemetry.sampling import _normalize_rate

        with caplog.at_level(logging.WARNING, logger="undef.telemetry.sampling"):
            result = _normalize_rate(1.5)

        assert result == 1.0
        assert "clamped" in caplog.text
        assert "1.5" in caplog.text

    def test_rate_below_zero_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        from undef.telemetry.sampling import _normalize_rate

        with caplog.at_level(logging.WARNING, logger="undef.telemetry.sampling"):
            result = _normalize_rate(-0.5)

        assert result == 0.0
        assert "clamped" in caplog.text

    def test_valid_rate_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        from undef.telemetry.sampling import _normalize_rate

        with caplog.at_level(logging.WARNING, logger="undef.telemetry.sampling"):
            result = _normalize_rate(0.5)

        assert result == 0.5
        assert "clamped" not in caplog.text


# ── OTLP header parsing warnings ────────────────────────────────────


class TestOTLPHeaderWarning:
    def test_malformed_pair_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        from undef.telemetry.config import _parse_otlp_headers

        with caplog.at_level(logging.WARNING, logger="undef.telemetry.config"):
            result = _parse_otlp_headers("good=value,bad-no-equals,another=ok")

        assert result == {"good": "value", "another": "ok"}
        assert "malformed OTLP header pair" in caplog.text
        assert "bad-no-equals" in caplog.text

    def test_empty_malformed_pair_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        from undef.telemetry.config import _parse_otlp_headers

        with caplog.at_level(logging.WARNING, logger="undef.telemetry.config"):
            result = _parse_otlp_headers("key=val,,")

        assert result == {"key": "val"}
        assert "malformed" not in caplog.text

    def test_trailing_comma_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        from undef.telemetry.config import _parse_otlp_headers

        with caplog.at_level(logging.WARNING, logger="undef.telemetry.config"):
            result = _parse_otlp_headers("key=val,")

        assert result == {"key": "val"}
        assert "malformed" not in caplog.text


# ── OTel debug logging ──────────────────────────────────────────────


class TestOTelDebugLogging:
    def test_has_otel_logs_debug_when_missing(self, caplog: pytest.LogCaptureFixture) -> None:
        from undef.telemetry._otel import has_otel

        with (
            patch("undef.telemetry._otel._import_module", side_effect=ImportError("no otel")),
            caplog.at_level(logging.DEBUG, logger="undef.telemetry._otel"),
        ):
            result = has_otel()

        assert result is False
        assert "no-op fallbacks" in caplog.text

    def test_load_trace_api_logs_debug_when_missing(self, caplog: pytest.LogCaptureFixture) -> None:
        from undef.telemetry._otel import load_otel_trace_api

        with (
            patch("undef.telemetry._otel._import_module", side_effect=ImportError("no trace")),
            caplog.at_level(logging.DEBUG, logger="undef.telemetry._otel"),
        ):
            result = load_otel_trace_api()

        assert result is None
        assert "no-op fallback" in caplog.text

    def test_load_metrics_api_logs_debug_when_missing(self, caplog: pytest.LogCaptureFixture) -> None:
        from undef.telemetry._otel import load_otel_metrics_api

        with (
            patch("undef.telemetry._otel._import_module", side_effect=ImportError("no metrics")),
            caplog.at_level(logging.DEBUG, logger="undef.telemetry._otel"),
        ):
            result = load_otel_metrics_api()

        assert result is None
        assert "no-op fallback" in caplog.text


# ── OTel SDK log noise suppression ─────────────────────────────────


class TestOTelSdkLogSuppression:
    def test_setup_quiets_otel_exporter_logger(self) -> None:
        from undef.telemetry.setup import _quiet_otel_sdk_loggers

        _quiet_otel_sdk_loggers()
        assert logging.getLogger("opentelemetry.exporter").level == logging.CRITICAL

    def test_setup_quiets_otel_sdk_logger(self) -> None:
        from undef.telemetry.setup import _quiet_otel_sdk_loggers

        _quiet_otel_sdk_loggers()
        assert logging.getLogger("opentelemetry.sdk").level == logging.CRITICAL


# ── Backwards compatibility ─────────────────────────────────────────


class TestBackwardsCompatibility:
    def test_config_errors_caught_by_value_error(self) -> None:
        """Existing code catching ValueError still works."""
        from undef.telemetry.config import LoggingConfig

        with pytest.raises(ValueError):
            LoggingConfig(level="INVALID_LEVEL")

    def test_event_schema_errors_caught_by_value_error(self) -> None:
        """Existing code catching ValueError for schema errors still works."""
        from undef.telemetry.schema.events import EventSchemaError, event_name

        with pytest.raises(ValueError):
            event_name("a")

        with pytest.raises(EventSchemaError):
            event_name("a")

    def test_catch_all_telemetry_errors(self) -> None:
        """TelemetryError catches both config and schema errors."""
        from undef.telemetry.config import _parse_env_float
        from undef.telemetry.schema.events import event_name

        with pytest.raises(TelemetryError):
            _parse_env_float("nope", "FIELD")

        with pytest.raises(TelemetryError):
            event_name("a")
