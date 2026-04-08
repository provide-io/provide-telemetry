# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for config secret masking."""

from __future__ import annotations

import pytest

from provide.telemetry.config import (
    LoggingConfig,
    MetricsConfig,
    TelemetryConfig,
    TracingConfig,
    _mask_endpoint_url,
    _mask_header_value,
    _mask_headers,
)

# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


def test_mask_header_value_short() -> None:
    assert _mask_header_value("short") == "****"
    assert _mask_header_value("1234567") == "****"  # exactly 7 chars — below threshold


def test_mask_header_value_exactly_8() -> None:
    assert _mask_header_value("12345678") == "1234****"


def test_mask_header_value_long() -> None:
    assert _mask_header_value("Bearer super-secret-token") == "Bear****"  # pragma: allowlist secret


def test_mask_headers_empty() -> None:
    assert _mask_headers({}) == {}


def test_mask_headers_masks_values() -> None:
    result = _mask_headers({"Authorization": "Bearer super-secret-token", "X-Key": "short"})  # pragma: allowlist secret
    assert result["Authorization"] == "Bear****"
    assert result["X-Key"] == "****"


def test_mask_endpoint_url_no_password() -> None:
    url = "https://otel.example.com/v1/traces"
    assert _mask_endpoint_url(url) == url


def test_mask_endpoint_url_with_password() -> None:
    url = "https://user:p4ssw0rd@otel.example.com/v1/traces"  # pragma: allowlist secret
    result = _mask_endpoint_url(url)
    assert "p4ssw0rd" not in result
    assert "****" in result
    assert "user" in result
    assert "otel.example.com" in result


def test_mask_endpoint_url_with_password_and_port() -> None:
    url = "https://user:p4ssw0rd@otel.example.com:4318/v1/traces"  # pragma: allowlist secret
    result = _mask_endpoint_url(url)
    assert "p4ssw0rd" not in result
    assert "4318" in result
    assert "****" in result


# ---------------------------------------------------------------------------
# Integration tests via repr / redacted_repr
# ---------------------------------------------------------------------------


def test_repr_masks_otlp_header_values() -> None:
    cfg = TelemetryConfig(
        logging=LoggingConfig(otlp_headers={"Authorization": "Bearer super-secret-token"}),  # pragma: allowlist secret
    )
    text = repr(cfg)
    assert "super-secret-token" not in text
    assert "****" in text


def test_repr_masks_endpoint_userinfo() -> None:
    cfg = TelemetryConfig(
        tracing=TracingConfig(
            otlp_endpoint="https://user:p4ssw0rd@otel.example.com/v1/traces",  # pragma: allowlist secret
        ),
    )
    text = repr(cfg)
    assert "p4ssw0rd" not in text
    assert "****" in text


def test_repr_masks_metrics_headers() -> None:
    cfg = TelemetryConfig(
        metrics=MetricsConfig(otlp_headers={"X-Api-Key": "sk-1234567890abcdef"}),  # pragma: allowlist secret
    )
    text = repr(cfg)
    assert "1234567890abcdef" not in text  # pragma: allowlist secret
    assert "****" in text


def test_repr_safe_with_no_secrets() -> None:
    cfg = TelemetryConfig()
    text = repr(cfg)
    assert "provide-service" in text  # default service_name visible


def test_redacted_repr_returns_string() -> None:
    cfg = TelemetryConfig(
        logging=LoggingConfig(otlp_headers={"X-Api-Key": "sk-1234567890abcdef"}),  # pragma: allowlist secret
    )
    safe = cfg.redacted_repr()
    assert isinstance(safe, str)
    assert "1234567890abcdef" not in safe  # pragma: allowlist secret


def test_short_header_value_fully_masked() -> None:
    cfg = TelemetryConfig(
        logging=LoggingConfig(otlp_headers={"X-Key": "short"}),
    )
    text = repr(cfg)
    assert "short" not in text
    assert "****" in text


def test_logging_config_repr_masks_headers() -> None:
    lc = LoggingConfig(otlp_headers={"Authorization": "Bearer longersecret"})  # pragma: allowlist secret
    text = repr(lc)
    assert "longersecret" not in text
    assert "Bear****" in text


def test_logging_config_repr_masks_endpoint() -> None:
    lc = LoggingConfig(otlp_endpoint="https://u:secret123@host.com")  # pragma: allowlist secret
    text = repr(lc)
    assert "secret123" not in text
    assert "****" in text


def test_tracing_config_repr_masks_headers() -> None:
    tc = TracingConfig(otlp_headers={"X-Token": "verylongtoken"})
    text = repr(tc)
    assert "verylongtoken" not in text
    assert "very****" in text


def test_tracing_config_repr_none_endpoint() -> None:
    tc = TracingConfig(otlp_endpoint=None)
    text = repr(tc)
    assert "None" in text


def test_metrics_config_repr_masks_headers() -> None:
    mc = MetricsConfig(otlp_headers={"X-Secret": "abcdefghij"})
    text = repr(mc)
    assert "abcdefghij" not in text
    assert "abcd****" in text


def test_metrics_config_repr_masks_endpoint() -> None:
    mc = MetricsConfig(otlp_endpoint="https://u:s3cretpw@metrics.example.com:4318")  # pragma: allowlist secret
    text = repr(mc)
    assert "s3cretpw" not in text
    assert "****" in text


def test_metrics_config_repr_none_endpoint() -> None:
    mc = MetricsConfig(otlp_endpoint=None)
    text = repr(mc)
    assert "None" in text


def test_masked_dataclass_repr_uses_comma_space_separator() -> None:
    """Kill mutmut_22: ', '.join(parts) -> 'XX, XX'.join(parts).

    Verify the repr uses standard comma-space separators between fields.
    """
    mc = MetricsConfig(otlp_endpoint=None, otlp_headers={})
    text = repr(mc)
    # The repr should contain ", " between fields, not "XX, XX"
    assert "XX, XX" not in text
    # Should look like: MetricsConfig(enabled=True, otlp_endpoint=None, otlp_headers={})
    assert ", " in text
    assert text.startswith("MetricsConfig(")
    assert text.endswith(")")


@pytest.mark.parametrize(
    "value,expected",
    [
        ("", "****"),
        ("abc", "****"),
        ("1234567", "****"),
        ("12345678", "1234****"),
        ("abcdefghijklmnop", "abcd****"),
    ],
)
def test_mask_header_value_parametrized(value: str, expected: str) -> None:
    assert _mask_header_value(value) == expected
