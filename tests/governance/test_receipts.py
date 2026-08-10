# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for cryptographic redaction receipts."""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from datetime import UTC, datetime

import pytest

from provide.telemetry import pii as pii_mod
from provide.telemetry.health import get_health_snapshot, reset_health_for_tests
from provide.telemetry.receipts import (
    TEST_RECEIPT_CAPACITY,
    MissingReceiptSinkError,
    RedactionReceipt,
    TestReceiptCollector,
    canonical_json,
    emit_receipt,
    enable_receipts,
    get_emitted_receipts_for_tests,
    receipt_timestamp,
    sign_receipt,
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


def test_receipt_original_hash_is_sha256_of_canonical_json() -> None:
    """original_hash is SHA-256 of the value's RFC 8785 form, not of str(value).

    Hashing the display form makes the string "1" and the integer 1 collide, so
    a receipt could not say which of the two was redacted.
    """
    enable_receipts(enabled=True, signing_key=None)
    payload = {"password": "secret123"}  # pragma: allowlist secret
    pii_mod.sanitize_payload(payload, enabled=True)
    receipts = get_emitted_receipts_for_tests()
    assert len(receipts) == 1
    expected_hash = hashlib.sha256(b'"secret123"').hexdigest()  # pragma: allowlist secret
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


def test_production_receipts_go_to_the_configured_sink_not_the_test_collector() -> None:
    """Outside test mode every receipt is delivered to the caller's sink."""
    import provide.telemetry.receipts as receipts_mod

    with receipts_mod._lock:
        receipts_mod._test_mode = False

    sink = TestReceiptCollector()
    enable_receipts(enabled=True, signing_key=None, service_name="prod-svc", sink=sink)
    payload = {"password": "secret123"}  # pragma: allowlist secret
    pii_mod.sanitize_payload(payload, enabled=True)

    assert [r.field_path for r in sink.receipts] == ["password"]
    assert get_emitted_receipts_for_tests() == []
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
    assert isinstance(ts, str)
    # Canonical shape: millisecond precision and a literal Z, which is what the
    # other SDKs emit. isoformat() would give microseconds and "+00:00".
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", ts), ts


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


def test_delivery_never_logs(caplog: pytest.LogCaptureFixture) -> None:
    """Receipt delivery emits no log record, successful or not.

    The logger produces redactions and redactions produce receipts, so a log
    line on this path is an unbounded log -> receipt -> log cycle.
    """
    import provide.telemetry.receipts as receipts_mod

    with receipts_mod._lock:
        receipts_mod._test_mode = False

    class _BrokenSink:
        def emit(self, receipt: object, /) -> bool:
            raise RuntimeError("sink down")

    reset_health_for_tests()
    with caplog.at_level(logging.DEBUG):
        enable_receipts(enabled=True, signing_key=None, service_name="log-svc", sink=_BrokenSink())
        payload = {"password": "secret123"}  # pragma: allowlist secret
        pii_mod.sanitize_payload(payload, enabled=True)

    assert caplog.records == []
    assert get_health_snapshot().receipt_failures == 1
    enable_receipts(enabled=False)


# ── Sinks, failure accounting, and the un-sinked path ────────────────────────


def _receipt() -> RedactionReceipt:
    return sign_receipt("v", receipt_id="r", timestamp="t", field_path="f", action="redact")


def test_a_sink_that_returns_false_counts_a_failure() -> None:
    class _Refusing:
        def emit(self, receipt: RedactionReceipt, /) -> bool:
            return False

    reset_health_for_tests()
    emit_receipt(_receipt(), _Refusing())
    assert get_health_snapshot().receipt_failures == 1


def test_a_sink_that_raises_counts_a_failure_and_does_not_propagate() -> None:
    class _Broken:
        def emit(self, receipt: RedactionReceipt, /) -> bool:
            raise RuntimeError("sink down")

    reset_health_for_tests()
    emit_receipt(_receipt(), _Broken())
    assert get_health_snapshot().receipt_failures == 1


def test_an_accepting_sink_counts_nothing() -> None:
    reset_health_for_tests()
    sink = TestReceiptCollector()
    emit_receipt(_receipt(), sink)
    assert get_health_snapshot().receipt_failures == 0
    assert len(sink.receipts) == 1


def test_enabling_receipts_in_production_without_a_sink_is_refused() -> None:
    """No sink, no enable — the full contract is pinned in
    test_receipts_sink_contract.py."""
    import provide.telemetry.receipts as receipts_mod

    with receipts_mod._lock:
        receipts_mod._test_mode = False

    with pytest.raises(MissingReceiptSinkError):
        enable_receipts(enabled=True, signing_key=None)
    assert pii_mod._receipt_hook is None


def test_disabling_receipts_in_production_needs_no_sink() -> None:
    import provide.telemetry.receipts as receipts_mod

    with receipts_mod._lock:
        receipts_mod._test_mode = False
    enable_receipts(enabled=False)
    assert pii_mod._receipt_hook is None


def test_the_sink_defaults_to_the_one_on_the_active_runtime_config() -> None:
    import provide.telemetry.receipts as receipts_mod
    from provide.telemetry.config import TelemetryConfig
    from provide.telemetry.runtime import apply_runtime_config

    sink = TestReceiptCollector()
    apply_runtime_config(TelemetryConfig(service_name="svc", receipt_sink=sink))
    with receipts_mod._lock:
        receipts_mod._test_mode = False

    enable_receipts(enabled=True, signing_key=None)
    pii_mod.sanitize_payload({"password": "s3cr3t"}, enabled=True)  # pragma: allowlist secret

    assert [r.field_path for r in sink.receipts] == ["password"]
    enable_receipts(enabled=False)


def test_a_hook_left_live_with_no_sink_counts_rather_than_delivering() -> None:
    """Defence in depth: enable_receipts installs the logging fallback instead of
    leaving the sink unset, so only a sink cleared underneath a live hook reaches it."""
    import provide.telemetry.receipts as receipts_mod

    enable_receipts(enabled=True, signing_key=None)
    with receipts_mod._lock:
        receipts_mod._test_mode = False
        receipts_mod._sink = None
    reset_health_for_tests()

    pii_mod.sanitize_payload({"password": "s3cr3t"}, enabled=True)  # pragma: allowlist secret

    assert get_health_snapshot().receipt_failures == 1
    enable_receipts(enabled=False)


def test_the_test_collector_is_bounded_and_drops_its_oldest() -> None:
    """Only the test collector is capped — a production sink is the caller's own store."""
    sink = TestReceiptCollector()
    for index in range(TEST_RECEIPT_CAPACITY + 5):
        sink.emit(sign_receipt(index, receipt_id=str(index), timestamp="t", field_path="f", action="drop"))

    assert len(sink.receipts) == TEST_RECEIPT_CAPACITY
    assert sink.receipts[0].receipt_id == "5"
    assert sink.receipts[-1].receipt_id == str(TEST_RECEIPT_CAPACITY + 4)


def test_receipt_timestamp_accepts_a_pinned_instant() -> None:
    moment = datetime(2026, 8, 4, 12, 34, 56, 789_012, tzinfo=UTC)
    assert receipt_timestamp(moment) == "2026-08-04T12:34:56.789Z"


def test_the_missing_sink_error_names_every_way_out() -> None:
    """Diagnosis plus all three remedies — the caller cannot act on half of it.

    Asserted whole rather than by substring: this message is the only thing a
    service owner sees at the moment receipts refuse to start, and losing the
    remedies to a rewording would leave them a complaint with no next step.
    """
    assert str(MissingReceiptSinkError()) == (
        "receipts are enabled but no receipt sink is configured; generated receipts "
        "would be signed and then discarded. Pass sink=... (LoggingReceiptSink() to "
        "deliver receipts as debug log lines), set TelemetryConfig.receipt_sink, or "
        "disable receipts."
    )


# ── RFC 8785 number and key rendering ───────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, "0"),
        (-0.0, "0"),
        (2.0, "2"),
        (1.5, "1.5"),
        (-1.5, "-1.5"),
        (100.0, "100"),
        (1e16, "10000000000000000"),
        (1e21, "1e+21"),
        (1.5e22, "1.5e+22"),
        (1e-6, "0.000001"),
        (1e-7, "1e-7"),
        (1.5e-7, "1.5e-7"),
        (float("nan"), "null"),
        (float("inf"), "null"),
        (float("-inf"), "null"),
    ],
)
def test_numbers_render_the_way_ecmascript_would(value: float, expected: str) -> None:
    """JCS is specified against ECMAScript, so repr() is not the answer."""
    assert canonical_json(value) == expected


def test_booleans_are_not_rendered_as_integers() -> None:
    """bool subclasses int, so an isinstance check alone would print True as 1."""
    assert canonical_json({"a": True, "b": False, "c": 1, "d": 0}) == '{"a":true,"b":false,"c":1,"d":0}'


def test_keys_are_ordered_by_utf16_code_unit() -> None:
    assert canonical_json({"é": 1, "b": 2, "A": 3, "10": 4}) == '{"10":4,"A":3,"b":2,"é":1}'


def test_key_order_is_utf16_code_unit_order_where_it_differs_from_code_point_order() -> None:
    """RFC 8785 section 3.2.3's own example, which exists to separate the two.

    Every key in the test above is BMP, and BMP keys sort the same either way,
    so a plain ``sorted()`` passes it and still disagrees with the other SDKs
    here. U+1F600 encodes as the surrogate pair D83D DE00, so by
    UTF-16 code unit it precedes U+FB33; by code point it follows it. Sorting by
    code point swaps the last two members and changes the receipt digest of any
    payload carrying an astral key.
    """
    assert canonical_json(
        {
            "€": "Euro Sign",
            "\r": "Carriage Return",
            "דּ": "Hebrew Letter Dalet With Dagesh",
            "}": "Right Curly Bracket",
            ",": "Comma",
            "\U0001f600": "Emoji: Grinning Face",
            "\u0080": "Control",
            "ö": "Latin Small Letter O With Diaeresis",
        }
    ) == (
        '{"\\r":"Carriage Return",'
        '",":"Comma",'
        '"}":"Right Curly Bracket",'
        '"\u0080":"Control",'
        '"ö":"Latin Small Letter O With Diaeresis",'
        '"€":"Euro Sign",'
        '"\U0001f600":"Emoji: Grinning Face",'
        '"דּ":"Hebrew Letter Dalet With Dagesh"}'
    )


def test_non_string_keys_are_stringified() -> None:
    assert canonical_json({2: "a", 10: "b"}) == '{"10":"b","2":"a"}'


def test_tuples_canonicalize_as_arrays() -> None:
    assert canonical_json((1, "a", None)) == '[1,"a",null]'


def test_values_json_cannot_represent_become_null() -> None:
    """Never raises: canonicalization runs inside the redaction hook."""
    assert canonical_json({"s": {1, 2}, "b": b"x"}) == '{"b":null,"s":null}'


def test_a_cycle_canonicalizes_instead_of_recursing_forever() -> None:
    node: dict[str, object] = {}
    node["self"] = node
    assert canonical_json(node) == '{"self":null}'

    items: list[object] = []
    items.append(items)
    assert canonical_json(items) == "[null]"


def test_a_shared_subtree_is_rendered_at_every_position() -> None:
    """Only a cycle collapses — the same subtree twice is not a cycle."""
    shared = {"k": 1}
    assert canonical_json({"a": shared, "b": shared}) == '{"a":{"k":1},"b":{"k":1}}'


def test_a_shared_list_is_rendered_at_every_position() -> None:
    """Same rule for sequences, and it is the exit from the walk that enforces it.

    The cycle guard adds each composite's identity on the way in and has to drop
    it again on the way out. A guard that only ever adds turns the second and
    every later appearance of one list into ``null``, so a payload holding the
    same list twice — the natural shape when a caller reuses a constant — loses
    a copy from its receipt digest.
    """
    shared = [1, 2]
    assert canonical_json([shared, shared]) == "[[1,2],[1,2]]"
    assert canonical_json({"a": shared, "b": shared}) == '{"a":[1,2],"b":[1,2]}'
