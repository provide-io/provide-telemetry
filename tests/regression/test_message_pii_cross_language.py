# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Cross-language regression: secrets embedded in log message strings must be
redacted by the value-based detector when sanitize=true.

Companion tests live in:
  * go/logger_handlers_test.go
      TestHandler_PIISanitization_MessageContent
      TestHandler_PIISanitization_MessageContent_WildcardRule
  * rust/src/logger/processors.rs (#[cfg(test)] mod tests)
  * typescript/tests/logger.pii-message.test.ts

The Python test below is the reference implementation — Go and Rust were
fixed separately to match this behaviour after a review found Go would
emit secrets verbatim in the message field.
"""

from __future__ import annotations

import io
import logging
import re
from collections.abc import Callable, Generator

import pytest

from provide.telemetry import get_logger, register_secret_pattern, setup_telemetry, shutdown_telemetry
from provide.telemetry.config import LoggingConfig, TelemetryConfig
from provide.telemetry.pii import reset_pii_rules_for_tests


def _capture_log_output(emit_fn: Callable[[], None]) -> str:
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        emit_fn()
    finally:
        root.removeHandler(handler)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _reset_telemetry() -> Generator[None, None, None]:
    reset_pii_rules_for_tests()
    yield
    shutdown_telemetry()
    reset_pii_rules_for_tests()


def test_python_redacts_secret_in_log_message_with_sanitize_enabled() -> None:
    """When sanitize=true, a secret embedded in the log message string must
    be replaced with the redaction sentinel '***'. The previous Go bug was
    that only attribute payloads were sanitized; the message went through
    verbatim. Python's structlog pipeline scans values (including the
    'event'/message field) for secret patterns by default."""
    cfg = TelemetryConfig(logging=LoggingConfig(fmt="json", sanitize=True))
    setup_telemetry(cfg)

    out = _capture_log_output(
        lambda: get_logger("test").info("token AKIAIOSFODNN7EXAMPLE leaked")  # pragma: allowlist secret
    )

    assert "AKIAIOSFODNN7EXAMPLE" not in out, (  # pragma: allowlist secret
        f"secret leaked in message: {out}"
    )
    assert '"message": "***"' in out, f"expected redacted message, got: {out}"


def test_python_emits_message_unchanged_when_sanitize_disabled() -> None:
    """When sanitize=false, secret patterns are not scanned and the message
    flows through. This documents the contract — sanitize is the gate."""
    cfg = TelemetryConfig(logging=LoggingConfig(fmt="json", sanitize=False))
    setup_telemetry(cfg)

    out = _capture_log_output(
        lambda: get_logger("test").info("token AKIAIOSFODNN7EXAMPLE leaked")  # pragma: allowlist secret
    )

    assert "AKIAIOSFODNN7EXAMPLE" in out, (  # pragma: allowlist secret
        f"sanitize=false should not scrub: {out}"
    )


def test_python_redacts_custom_secret_pattern_in_log_message() -> None:
    """Registered custom secret patterns must also apply to free-form messages."""
    register_secret_pattern("internal_token", re.compile(r"INTSECRET-[A-Z0-9]{12,}"))
    cfg = TelemetryConfig(logging=LoggingConfig(fmt="json", sanitize=True))
    setup_telemetry(cfg)

    out = _capture_log_output(lambda: get_logger("test").info("token INTSECRET-ABC123XYZ789 leaked"))

    assert "INTSECRET-ABC123XYZ789" not in out, f"custom secret leaked in message: {out}"
    assert '"message": "***"' in out, f"expected redacted custom-secret message, got: {out}"
