# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Enabling receipts with no sink is refused; LoggingReceiptSink is the opt-in.

All five SDKs refuse the enable-without-sink combination identically: an audit
trail with no destination is a silent no-op, so the misconfiguration surfaces
at enable time instead of degrading. A service whose log stream is its receipt
destination says so explicitly with ``sink=LoggingReceiptSink()``.
"""

from __future__ import annotations

import logging

import pytest

from provide.telemetry import pii as pii_mod
from provide.telemetry import receipts as receipts_mod
from provide.telemetry.exceptions import ConfigurationError
from provide.telemetry.health import get_health_snapshot, reset_health_for_tests
from provide.telemetry.receipts import (
    LoggingReceiptSink,
    MissingReceiptSinkError,
    RedactionReceipt,
    TestReceiptCollector,
    enable_receipts,
    get_emitted_receipts_for_tests,
)

_RECEIPTS_LOGGER = "provide.telemetry.receipts"


@pytest.fixture(autouse=True)
def _reset() -> None:
    pii_mod.reset_pii_rules_for_tests()
    receipts_mod._reset_receipts_for_tests()


def _leave_test_mode() -> None:
    with receipts_mod._lock:
        receipts_mod._test_mode = False


def _receipts_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == _RECEIPTS_LOGGER]


def test_enable_without_a_sink_is_refused() -> None:
    _leave_test_mode()

    with pytest.raises(MissingReceiptSinkError):
        enable_receipts(enabled=True, signing_key="k", service_name="svc")


def test_a_refused_enable_leaves_receipts_fully_disabled() -> None:
    """The raise happens before any state assignment — no half-enabled hook."""
    _leave_test_mode()

    with pytest.raises(MissingReceiptSinkError):
        enable_receipts(enabled=True, signing_key="k", service_name="svc")

    assert pii_mod._receipt_hook is None
    assert receipts_mod._enabled is False
    assert receipts_mod._sink is None
    assert receipts_mod._signing_key is None


def test_the_refusal_names_the_ways_out() -> None:
    """The error is a ConfigurationError and tells the operator what to pass."""
    _leave_test_mode()

    with pytest.raises(ConfigurationError, match="LoggingReceiptSink") as excinfo:
        enable_receipts(enabled=True, signing_key=None)

    assert "TelemetryConfig.receipt_sink" in str(excinfo.value)


def test_disabling_without_a_sink_always_succeeds() -> None:
    _leave_test_mode()
    enable_receipts(enabled=False)
    assert pii_mod._receipt_hook is None


def test_logging_receipt_sink_delivers_each_receipt_as_a_debug_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _leave_test_mode()
    enable_receipts(enabled=True, signing_key="k", service_name="svc", sink=LoggingReceiptSink())
    assert pii_mod._receipt_hook is not None

    with caplog.at_level(logging.DEBUG, logger=_RECEIPTS_LOGGER):
        pii_mod.sanitize_payload({"password": "s3cr3t"}, enabled=True)  # pragma: allowlist secret

    lines = [r for r in _receipts_records(caplog) if r.levelno == logging.DEBUG]
    assert len(lines) == 1
    message = lines[0].getMessage()
    assert message.startswith("telemetry.receipt ")
    assert "field=password" in message
    assert "action=redact" in message
    assert "s3cr3t" not in message  # only the hash travels, never the value
    enable_receipts(enabled=False)


def test_logging_receipt_sink_line_carries_every_receipt_field(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The whole line, exactly — a dropped field is an audit record missing data."""
    receipt = RedactionReceipt(
        receipt_id="rid-1",
        timestamp="2026-08-10T00:00:00+00:00",
        service_name="svc",
        field_path="user.password",
        action="redact",
        original_hash="hash-abc",
        hmac="mac-def",
    )
    with caplog.at_level(logging.DEBUG, logger=_RECEIPTS_LOGGER):
        assert LoggingReceiptSink().emit(receipt) is True

    [record] = _receipts_records(caplog)
    assert record.getMessage() == (
        "telemetry.receipt id=rid-1 ts=2026-08-10T00:00:00+00:00 "
        "field=user.password action=redact hash=hash-abc hmac=mac-def"
    )


def test_logging_receipt_sink_counts_no_failures() -> None:
    """emit() accepts, so health reports a working audit path."""
    _leave_test_mode()
    enable_receipts(enabled=True, signing_key=None, sink=LoggingReceiptSink())
    reset_health_for_tests()

    pii_mod.sanitize_payload({"password": "x"}, enabled=True)

    assert get_health_snapshot().receipt_failures == 0
    enable_receipts(enabled=False)


def test_an_explicit_collector_sink_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    _leave_test_mode()
    sink = TestReceiptCollector()
    with caplog.at_level(logging.DEBUG, logger=_RECEIPTS_LOGGER):
        enable_receipts(enabled=True, signing_key=None, service_name="svc", sink=sink)
        pii_mod.sanitize_payload({"password": "s3cr3t"}, enabled=True)  # pragma: allowlist secret

    assert [r.field_path for r in sink.receipts] == ["password"]
    assert _receipts_records(caplog) == []
    enable_receipts(enabled=False)


def test_the_runtime_config_sink_satisfies_the_requirement(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from provide.telemetry.config import TelemetryConfig
    from provide.telemetry.runtime import apply_runtime_config

    sink = TestReceiptCollector()
    apply_runtime_config(TelemetryConfig(service_name="svc", receipt_sink=sink))
    _leave_test_mode()
    with caplog.at_level(logging.DEBUG, logger=_RECEIPTS_LOGGER):
        enable_receipts(enabled=True, signing_key=None)
        pii_mod.sanitize_payload({"password": "s3cr3t"}, enabled=True)  # pragma: allowlist secret

    assert [r.field_path for r in sink.receipts] == ["password"]
    assert _receipts_records(caplog) == []
    enable_receipts(enabled=False)


def test_the_test_mode_path_needs_no_sink(caplog: pytest.LogCaptureFixture) -> None:
    """In test mode the built-in collector stands in for a configured sink."""
    with caplog.at_level(logging.DEBUG, logger=_RECEIPTS_LOGGER):
        enable_receipts(enabled=True, signing_key=None, service_name="test-svc")
        pii_mod.sanitize_payload({"password": "x"}, enabled=True)

    assert [r.field_path for r in get_emitted_receipts_for_tests()] == ["password"]
    assert _receipts_records(caplog) == []
