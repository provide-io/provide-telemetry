# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Endpoint masking survives URLs the parser rejects, and never leaks the password.

``urlparse(url).port`` raises ``ValueError`` on a non-numeric or out-of-range
port, so ``repr(config)`` -- and every diagnostic that prints a config -- raised
on exactly the malformed endpoint an operator most needs to see.
"""

from __future__ import annotations

import pytest

from provide.telemetry._masking import _mask_endpoint_url, redact_config
from provide.telemetry.config import TelemetryConfig, TracingConfig

_PASSWORD = "p4ssw0rd"  # pragma: allowlist secret


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://u:p4ssw0rd@h:bad", "http://u:****@h:bad"),  # pragma: allowlist secret
        ("http://u:p4ssw0rd@h:99999/v1/logs", "http://u:****@h:99999/v1/logs"),  # pragma: allowlist secret
        ("http://u:p4ssw0rd@[::1/v1", "http://u:****@[::1/v1"),  # pragma: allowlist secret
        ("u:p4ssw0rd@h:bad", "u:****@h:bad"),  # pragma: allowlist secret
        ("http://u:p4ssw0rd@h:bad?q=1#f", "http://u:****@h:bad?q=1#f"),  # pragma: allowlist secret
    ],
    ids=["non-numeric-port", "port-out-of-range", "broken-ipv6", "no-scheme", "query-and-fragment"],
)
def test_malformed_endpoint_is_masked_without_raising(url: str, expected: str) -> None:
    masked = _mask_endpoint_url(url)
    assert masked == expected
    assert _PASSWORD not in masked


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://user:p4ssw0rd@Otel.Example.com:4318/v1/traces",  # pragma: allowlist secret
            "https://user:****@Otel.Example.com:4318/v1/traces",
        ),
        ("http://u:p4ssw0rd@[::1]:4318/v1", "http://u:****@[::1]:4318/v1"),  # pragma: allowlist secret
        ("http://u:p:w@h/v1", "http://u:****@h/v1"),  # pragma: allowlist secret
        ("http://u:pa@ss@h/v1", "http://u:****@h/v1"),  # pragma: allowlist secret
    ],
    ids=["host-case-kept", "ipv6-brackets-kept", "colon-in-password", "at-in-password"],
)
def test_well_formed_endpoint_masks_only_the_password(url: str, expected: str) -> None:
    assert _mask_endpoint_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://otel.example.com/v1/traces",
        "https://user@otel.example.com/v1/traces",
        "https://otel.example.com/path:with@sign",  # pragma: allowlist secret
        "http://h:bad/v1",
        "http://u:@h/v1",
        "u:@h:bad",
        "not a url at all",
        "",
    ],
    ids=[
        "no-userinfo",
        "user-only",
        "at-in-path",
        "malformed-no-userinfo",
        "empty-password",
        "empty-password-malformed",
        "free-text",
        "empty",
    ],
)
def test_endpoint_without_a_password_is_returned_unchanged(url: str) -> None:
    assert _mask_endpoint_url(url) == url


def test_repr_and_redact_config_survive_a_malformed_endpoint() -> None:
    cfg = TelemetryConfig(
        tracing=TracingConfig(otlp_endpoint="http://u:p4ssw0rd@h:bad/v1/traces")
    )  # pragma: allowlist secret
    text = repr(cfg)
    assert _PASSWORD not in text
    assert "u:****@h:bad" in text
    tracing = redact_config(cfg)["tracing"]
    assert isinstance(tracing, dict)
    assert tracing["otlp_endpoint"] == "http://u:****@h:bad/v1/traces"
