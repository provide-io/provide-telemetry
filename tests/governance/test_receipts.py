# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for cryptographic redaction receipts."""

from __future__ import annotations

import hashlib
import hmac
import logging

import pytest

from provide.telemetry import pii as pii_mod
from provide.telemetry.receipts import (
    enable_receipts,
    get_emitted_receipts_for_tests,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    pii_mod.reset_pii_rules_for_tests()
    from provide.telemetry.receipts import _reset_receipts_for_tests

    _reset_receipts_for_tests()


def test_receipts_disabled_by_default() -> None:
    """Receipt hook is None by default; no receipts emitted after sanitize."""
    payload = {"password": "secret123"}  # pragma: allowlist secret
    pii_mod.sanitize_payload(payload, enabled=True)
    receipts = get_emitted_receipts_for_tests()
    assert receipts == []


def test_receipts_emitted_when_enabled() -> None:
    """Receipts are generated when enabled and a sensitive field is sanitized."""
    enable_receipts(enabled=True, signing_key=None, service_name="test-svc")
    payload = {"password": "secret123"}  # pragma: allowlist secret
    pii_mod.sanitize_payload(payload, enabled=True)
    receipts = get_emitted_receipts_for_tests()
    assert len(receipts) == 1
    r = receipts[0]
    assert r.field_path == "password"
    assert r.action == "redact"
    assert len(r.receipt_id) > 0


def test_receipt_original_hash_is_sha256() -> None:
    """The original_hash field is SHA-256 of the string representation of the value."""
    enable_receipts(enabled=True, signing_key=None)
    payload = {"password": "secret123"}  # pragma: allowlist secret
    pii_mod.sanitize_payload(payload, enabled=True)
    receipts = get_emitted_receipts_for_tests()
    assert len(receipts) == 1
    expected_hash = hashlib.sha256(b"secret123").hexdigest()  # pragma: allowlist secret
    assert receipts[0].original_hash == expected_hash


def test_receipt_hmac_when_key_provided() -> None:
    """HMAC is correctly computed when a signing key is provided."""
    enable_receipts(enabled=True, signing_key="test-key")
    payload = {"password": "secret123"}  # pragma: allowlist secret
    pii_mod.sanitize_payload(payload, enabled=True)
    receipts = get_emitted_receipts_for_tests()
    assert len(receipts) == 1
    r = receipts[0]
    assert r.hmac != ""
    payload_str = f"{r.receipt_id}|{r.timestamp}|{r.field_path}|{r.action}|{r.original_hash}"
    expected_hmac = hmac.new(b"test-key", payload_str.encode("utf-8"), hashlib.sha256).hexdigest()
    assert r.hmac == expected_hmac


def test_receipt_hmac_empty_when_no_key() -> None:
    """HMAC is empty string when no signing key is provided."""
    enable_receipts(enabled=True, signing_key=None)
    payload = {"password": "secret123"}  # pragma: allowlist secret
    pii_mod.sanitize_payload(payload, enabled=True)
    receipts = get_emitted_receipts_for_tests()
    assert len(receipts) == 1
    assert receipts[0].hmac == ""


def test_receipt_tamper_detection() -> None:
    """Changing field_path after signing produces a different HMAC."""
    enable_receipts(enabled=True, signing_key="test-key")
    payload = {"password": "secret123"}  # pragma: allowlist secret
    pii_mod.sanitize_payload(payload, enabled=True)
    receipts = get_emitted_receipts_for_tests()
    assert len(receipts) == 1
    r = receipts[0]
    # Compute HMAC with a tampered field_path
    tampered_payload = f"{r.receipt_id}|{r.timestamp}|tampered.path|{r.action}|{r.original_hash}"
    tampered_hmac = hmac.new(b"test-key", tampered_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    assert r.hmac != tampered_hmac


def test_enable_receipts_disabled() -> None:
    """Calling enable_receipts(enabled=False) unregisters the hook."""
    enable_receipts(enabled=True)
    assert pii_mod._receipt_hook is not None
    enable_receipts(enabled=False)
    assert pii_mod._receipt_hook is None


def test_receipt_id_is_uuid_format() -> None:
    """receipt_id is a UUID4 string: 36 chars with dashes at positions 8,13,18,23."""
    enable_receipts(enabled=True)
    payload = {"password": "secret123"}  # pragma: allowlist secret
    pii_mod.sanitize_payload(payload, enabled=True)
    receipts = get_emitted_receipts_for_tests()
    assert len(receipts) == 1
    rid = receipts[0].receipt_id
    assert len(rid) == 36
    assert rid[8] == "-"
    assert rid[13] == "-"
    assert rid[18] == "-"
    assert rid[23] == "-"


def test_receipts_not_emitted_outside_test_mode() -> None:
    """enable_receipts works without crash even when _test_mode is False (production path)."""
    import provide.telemetry.receipts as receipts_mod

    # Directly set _test_mode to False to simulate production mode
    with receipts_mod._lock:
        receipts_mod._test_mode = False

    enable_receipts(enabled=True, signing_key=None, service_name="prod-svc")
    payload = {"password": "secret123"}  # pragma: allowlist secret
    # Should not raise and should not add to test_receipts
    pii_mod.sanitize_payload(payload, enabled=True)
    # In non-test mode, receipts are logged, not stored
    with receipts_mod._lock:
        assert receipts_mod._test_receipts == []
    # cleanup
    enable_receipts(enabled=False)


def test_enable_receipts_default_enabled_is_true() -> None:
    """Calling enable_receipts() with no args enables receipts (default enabled=True)."""
    enable_receipts()
    assert pii_mod._receipt_hook is not None
    payload = {"password": "secret123"}  # pragma: allowlist secret
    pii_mod.sanitize_payload(payload, enabled=True)
    receipts = get_emitted_receipts_for_tests()
    assert len(receipts) == 1


def test_enable_receipts_default_service_name() -> None:
    """Default service_name is 'unknown' and appears on receipts."""
    enable_receipts(enabled=True)
    payload = {"password": "secret123"}  # pragma: allowlist secret
    pii_mod.sanitize_payload(payload, enabled=True)
    receipts = get_emitted_receipts_for_tests()
    assert len(receipts) == 1
    assert receipts[0].service_name == "unknown"


def test_receipt_service_name_propagated() -> None:
    """service_name passed to enable_receipts appears on each receipt."""
    enable_receipts(enabled=True, signing_key=None, service_name="my-svc")
    payload = {"password": "secret123"}  # pragma: allowlist secret
    pii_mod.sanitize_payload(payload, enabled=True)
    receipts = get_emitted_receipts_for_tests()
    assert len(receipts) == 1
    assert receipts[0].service_name == "my-svc"


def test_receipt_timestamp_is_utc_iso_string() -> None:
    """Receipt timestamp is a non-None ISO 8601 string with UTC offset."""
    enable_receipts(enabled=True)
    payload = {"password": "secret123"}  # pragma: allowlist secret
    pii_mod.sanitize_payload(payload, enabled=True)
    receipts = get_emitted_receipts_for_tests()
    assert len(receipts) == 1
    ts = receipts[0].timestamp
    assert ts is not None
    assert isinstance(ts, str)
    assert "+00:00" in ts


def test_reset_clears_signing_key_to_none() -> None:
    """After _reset_receipts_for_tests, signing_key is None (not empty string)."""
    import provide.telemetry.receipts as receipts_mod

    enable_receipts(enabled=True, signing_key="some-key")
    receipts_mod._reset_receipts_for_tests()
    # Re-enable without explicit key — should use None from reset
    enable_receipts(enabled=True)
    payload = {"password": "secret123"}  # pragma: allowlist secret
    pii_mod.sanitize_payload(payload, enabled=True)
    receipts = get_emitted_receipts_for_tests()
    assert len(receipts) == 1
    # With signing_key=None, HMAC should be empty
    assert receipts[0].hmac == ""


def test_production_mode_log_message_and_extras(caplog: pytest.LogCaptureFixture) -> None:
    """In production mode, receipt is logged with correct message and extra fields."""
    import provide.telemetry.receipts as receipts_mod

    with receipts_mod._lock:
        receipts_mod._test_mode = False

    with caplog.at_level(logging.DEBUG, logger="provide.telemetry.receipts"):
        enable_receipts(enabled=True, signing_key=None, service_name="log-svc")
        payload = {"password": "secret123"}  # pragma: allowlist secret
        pii_mod.sanitize_payload(payload, enabled=True)

    assert len(caplog.records) >= 1
    record = caplog.records[0]
    assert record.message == "provide.pii.redaction_receipt"
    assert record.receipt_id is not None  # type: ignore[attr-defined]
    assert record.field_path == "password"  # type: ignore[attr-defined]
    # cleanup
    enable_receipts(enabled=False)
