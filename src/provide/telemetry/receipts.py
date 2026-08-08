# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Cryptographic redaction receipts.

Registers a receipt hook on the PII engine when enabled; delete this module and
the engine runs unchanged, because the hook stays ``None``.

Two cross-language contracts live here:

* **Canonicalization** — the hashed form of a redacted value is its RFC 8785
  (JCS) serialization, not ``str(value)``. Hashing the display form collides
  across types: the string ``"1"`` and the integer ``1`` render identically and
  so produce the same digest, which makes the receipt unable to say which was
  redacted.
* **Signing** — ``receipt_id|timestamp|field_path|action|original_hash`` under
  HMAC-SHA256, lowercase hex.

Both are pinned by ``spec/receipt_fixtures.yaml``, whose vectors come from
independent implementations, so reproducing them means agreeing with the other
SDKs rather than agreeing with ourselves. Note that ``json.dumps`` is *not* a
JCS implementation: it emits ``-0.0`` where JCS requires ``0``.
"""

from __future__ import annotations

__all__ = [
    "TEST_RECEIPT_CAPACITY",
    "MissingReceiptSinkError",
    "ReceiptSink",
    "RedactionReceipt",
    "TestReceiptCollector",
    "canonical_json",
    "emit_receipt",
    "enable_receipts",
    "get_emitted_receipts_for_tests",
    "receipt_payload",
    "sign_receipt",
]

import hashlib
import hmac as hmac_mod
import json
import math
import threading
import uuid
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from provide.telemetry import pii as pii_mod
from provide.telemetry.exceptions import ConfigurationError
from provide.telemetry.health import increment_receipt_failures


@dataclass(frozen=True, slots=True)
class RedactionReceipt:
    receipt_id: str
    timestamp: str
    service_name: str
    field_path: str
    action: str
    original_hash: str
    hmac: str


@runtime_checkable
class ReceiptSink(Protocol):
    """Destination for governance receipts.

    ``emit`` returns False to reject a receipt. Returning False and raising both
    count a ``receipt_failures``; neither is logged — see :func:`emit_receipt`.
    """

    def emit(self, receipt: RedactionReceipt, /) -> bool: ...


class MissingReceiptSinkError(ConfigurationError):
    """Receipts were enabled outside test mode with nowhere to deliver them."""

    def __init__(self) -> None:
        super().__init__(
            "receipts are enabled but no receipt sink is configured; generated receipts "
            "would be signed and then discarded. Pass sink=..., set "
            "TelemetryConfig.receipt_sink, or disable receipts."
        )


#: Retention cap for :class:`TestReceiptCollector`.
TEST_RECEIPT_CAPACITY = 1024


class TestReceiptCollector:
    """In-memory sink for tests, bounded at :data:`TEST_RECEIPT_CAPACITY`.

    Only the *test* collector is capped. A production sink is the caller's own
    durable destination, and quietly discarding audit records to stay inside a
    memory budget is not a decision this library gets to make for them.
    """

    # Named for its role, not for pytest: without this, collection warns about
    # a "Test*" class it cannot instantiate.
    __test__ = False

    __slots__ = ("receipts",)

    def __init__(self) -> None:
        self.receipts: deque[RedactionReceipt] = deque(maxlen=TEST_RECEIPT_CAPACITY)

    def emit(self, receipt: RedactionReceipt, /) -> bool:
        self.receipts.append(receipt)
        return True


# ── RFC 8785 (JCS) canonicalization ─────────────────────────────────────────
#
# JCS was written against ECMAScript, so the parts of it Python does not give
# away for free are the number rendering (ECMAScript's Number::toString, not
# repr) and the key ordering (UTF-16 code units, not code points). String
# escaping is the one piece that matches: json.dumps escapes exactly the set
# JSON.stringify does.


def _format_significand(digits: str, n: int) -> str:
    """Render ECMAScript's (digits, n) decimal form, per Number::toString."""
    k = len(digits)
    if k <= n <= 21:
        return digits + "0" * (n - k)
    if 0 < n <= 21:
        return digits[:n] + "." + digits[n:]
    # ECMAScript spells this bound "-6 < n <= 0", and both halves are load
    # bearing. Dropping "n <= 0" as redundant — on the reasoning that the
    # branches above consume every positive n — is wrong: they only consume
    # n <= 21, so n = 22 fell through to here, "0" * -22 produced the empty
    # string, and 1e21 rendered as "0.1". 1e21, 1e22 and 0.1 then shared one
    # canonical form and one receipt digest. Restated in full, deliberately.
    if -6 < n <= 0:
        return "0." + "0" * -n + digits
    # Only n > 21 or n <= -6 reach this, so the exponent is never zero and the
    # sign flag renders exactly the explicit "+" ECMAScript emits — the same
    # rule go/canonicaljson.go's canonicalExponent and rust/src/jcs.rs apply.
    exponent = n - 1
    mantissa = digits if k == 1 else digits[0] + "." + digits[1:]
    return f"{mantissa}e{exponent:+d}"


def _format_number(value: float) -> str:
    """Render a finite float the way ECMAScript would, which is what JCS means.

    ``repr`` is already the shortest round-tripping decimal, so the work left is
    reshaping it: ``2.0`` must print as ``2``, ``-0.0`` as ``0`` (the
    ``negative_zero_collapses`` vector), and the exponent thresholds must be
    ECMAScript's rather than Python's.
    """
    if value == 0:
        return "0"
    parts = Decimal(repr(value)).as_tuple()
    sign = "-" if parts.sign else ""
    digits = list(parts.digits)
    exponent = int(parts.exponent)
    # Zero is already gone, so the leading digit is nonzero and the pop
    # terminates without a length guard.
    while digits[-1] == 0:
        digits.pop()
        exponent += 1
    text = "".join(str(digit) for digit in digits)
    return sign + _format_significand(text, exponent + len(text))


def _sort_key(key: str) -> bytes:
    """JCS orders object keys by UTF-16 code unit, not by code point."""
    # Codec lookup is case-insensitive, so a "UTF-16-BE" mutation selects the
    # same codec and yields identical bytes.
    return key.encode("utf-16-be")  # pragma: no mutate


def _json_string(text: str) -> str:
    """Quote and escape a string exactly as ``JSON.stringify`` does.

    This is the one piece of JCS Python gives away for free: ``json.dumps``
    escapes precisely the set ECMAScript does, so only the ASCII-escaping has
    to be turned off.
    """
    # ensure_ascii is read for truth, so the falsy-mutant (None) is the same
    # flag value and cannot change a byte of the output.
    return json.dumps(text, ensure_ascii=False)  # pragma: no mutate


def _canonical(value: Any, seen: set[int]) -> str:
    if value is None:
        return "null"
    # Checked by identity and before int: bool is an int subclass, so an
    # isinstance test would render True as 1.
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _json_string(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # NaN and ±Infinity have no JSON encoding. The fixtures fix `null` as
        # the spelling so each SDK does not invent its own.
        if not math.isfinite(value):
            return "null"
        return _format_number(value)
    if isinstance(value, Mapping):
        return _canonical_mapping(value, seen)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return _canonical_sequence(value, seen)
    # Anything JSON cannot represent. Never raises: canonicalization runs inside
    # the redaction hook, so raising would turn a log call into an exception.
    # In the normal pipeline hardening has already replaced these with '***';
    # this covers a direct sign_receipt() call.
    return "null"


def _canonical_mapping(value: Mapping[Any, Any], seen: set[int]) -> str:
    if id(value) in seen:
        return "null"
    seen.add(id(value))
    try:
        # Rendered names are paired with their values up front: a non-string key
        # canonicalizes under str(key), which is no longer a key of the mapping.
        pairs = sorted(((str(key), item) for key, item in value.items()), key=lambda pair: _sort_key(pair[0]))
        body = ",".join(f"{_json_string(name)}:{_canonical(item, seen)}" for name, item in pairs)
        return "{" + body + "}"
    finally:
        seen.discard(id(value))


def _canonical_sequence(value: Sequence[Any], seen: set[int]) -> str:
    if id(value) in seen:
        return "null"
    seen.add(id(value))
    try:
        return "[" + ",".join(_canonical(item, seen) for item in value) + "]"
    finally:
        seen.discard(id(value))


def canonical_json(value: Any) -> str:
    """Serialize *value* to its RFC 8785 canonical JSON form.

    A composite reached twice on one path — a cycle — canonicalizes to ``null``
    rather than recursing forever. Hardening replaces cycles with ``'***'``
    before they get here; this is the backstop for a direct call.
    """
    return _canonical(value, set())


def receipt_payload(receipt_id: str, timestamp: str, field_path: str, action: str, original_hash: str) -> str:
    """The canonical signing payload, in the byte order every SDK signs."""
    return "|".join([receipt_id, timestamp, field_path, action, original_hash])


def receipt_timestamp(moment: datetime | None = None) -> str:
    """Format an instant as the canonical receipt timestamp.

    Millisecond precision with a literal ``Z``. ``datetime.isoformat`` gives
    microseconds and ``+00:00``, neither of which the other SDKs produce.
    """
    when = moment if moment is not None else datetime.now(tz=UTC)
    milliseconds = when.microsecond // 1000
    return f"{when.strftime('%Y-%m-%dT%H:%M:%S')}.{milliseconds:03d}Z"


def sign_receipt(
    value: Any,
    *,
    receipt_id: str,
    timestamp: str,
    field_path: str,
    action: str,
    service_name: str = "unknown",
    key: bytes | None = None,
) -> RedactionReceipt:
    """Build a receipt over *value*, canonicalizing and signing it.

    Every identity-bearing field is a parameter rather than being generated
    here, so ``spec/receipt_fixtures.yaml`` can be reproduced exactly.
    """
    # Codec lookup is case-insensitive, so an "UTF-8" mutation selects the same
    # codec and produces an identical digest.
    canonical = canonical_json(value).encode("utf-8")  # pragma: no mutate
    original_hash = hashlib.sha256(canonical).hexdigest()
    signature = ""
    if key:
        payload = receipt_payload(receipt_id, timestamp, field_path, action, original_hash)
        payload_bytes = payload.encode("utf-8")  # pragma: no mutate — codec alias equivalent
        signature = hmac_mod.new(key, payload_bytes, hashlib.sha256).hexdigest()
    return RedactionReceipt(
        receipt_id=receipt_id,
        timestamp=timestamp,
        service_name=service_name,
        field_path=field_path,
        action=action,
        original_hash=original_hash,
        hmac=signature,
    )


def emit_receipt(receipt: RedactionReceipt, sink: ReceiptSink) -> None:
    """Hand a receipt to its sink, counting refusals.

    This path must never log. The logger is what produces redactions,
    redactions are what produce receipts, and a sink that fails on every
    receipt would then drive an unbounded log → receipt → log cycle. A refusal
    is recorded only as a counter, which ``get_health_snapshot().receipt_failures``
    exposes.
    """
    try:
        accepted = sink.emit(receipt)
    except Exception:
        # Counted, never logged, and never re-raised: a sink that raises must
        # not take the caller's log call down with it. `accepted` is only read
        # for truth below, so the falsy-mutant (None) counts the same failure.
        accepted = False  # pragma: no mutate
    if not accepted:
        increment_receipt_failures()


_lock = threading.Lock()
_enabled: bool = False
_signing_key: str | None = None
_service_name: str = "unknown"
_sink: ReceiptSink | None = None
_test_mode: bool = False
_test_collector = TestReceiptCollector()


def _resolve_sink(sink: ReceiptSink | None, *, enabled: bool) -> ReceiptSink | None:
    """Fall back to the sink on the active runtime config.

    Only when enabling. Reading the runtime config falls back to
    ``TelemetryConfig.from_env()``, which raises on a malformed environment,
    and a call that is switching receipts *off* must always succeed.
    """
    if sink is not None or not enabled:
        return sink
    from provide.telemetry.runtime import get_runtime_config

    return get_runtime_config().receipt_sink


def enable_receipts(
    enabled: bool = True,  # pragma: no mutate — all callers pass explicitly
    signing_key: str | None = None,
    service_name: str = "unknown",  # pragma: no mutate — all callers pass explicitly
    sink: ReceiptSink | None = None,
) -> None:
    """Enable or disable receipt generation.

    *sink* defaults to ``TelemetryConfig.receipt_sink`` on the active runtime
    config. Enabling receipts outside test mode without either raises: the
    alternative computes a full signed receipt for every redaction and drops it
    on the floor, so a service can believe it has an audit trail and have none.
    """
    global _enabled, _signing_key, _service_name, _sink
    resolved = _resolve_sink(sink, enabled=enabled)
    if enabled and not _test_mode and resolved is None:
        raise MissingReceiptSinkError
    with _lock:
        _enabled = enabled  # pragma: no mutate — direct assignment; read-back asserted by enable_receipts tests
        _signing_key = signing_key
        _service_name = service_name
        _sink = resolved
    if enabled:
        pii_mod._receipt_hook = _on_redaction
    else:
        pii_mod._receipt_hook = None


def _on_redaction(field_path: str, action: str, original_value: Any) -> None:
    with _lock:
        key = _signing_key
        service_name = _service_name
        # In test mode the built-in collector stands in for a configured sink,
        # so the suite never exercises the un-sinked path enable_receipts now
        # rejects.
        sink = _test_collector if _test_mode else _sink
    # Hoisted out of the call below because a pragma on a continuation line is
    # ignored; the codec name is an alias, so the mutation cannot change bytes.
    signing_key = key.encode("utf-8") if key else None  # pragma: no mutate
    receipt = sign_receipt(
        original_value,
        receipt_id=str(uuid.uuid4()),
        timestamp=receipt_timestamp(),
        field_path=field_path,
        action=action,
        service_name=service_name,
        key=signing_key,
    )
    if sink is None:
        # enable_receipts refuses this combination, so reaching it means the
        # sink was cleared underneath a live hook. Counted, not logged.
        increment_receipt_failures()
        return
    emit_receipt(receipt, sink)


def get_emitted_receipts_for_tests() -> list[RedactionReceipt]:
    with _lock:
        return list(_test_collector.receipts)


def _reset_receipts_for_tests() -> None:
    global _enabled, _signing_key, _test_mode, _sink
    with _lock:
        _enabled = False  # pragma: no mutate — test reset; False is the canonical disabled value
        _signing_key = None  # pragma: no mutate — "" is equivalent (both falsy for HMAC check)
        # Hygiene only: the same call latches test mode, and _on_redaction
        # routes to _test_collector while that holds, so nothing reads _sink
        # until enable_receipts sets it again.
        _sink = None  # pragma: no mutate
        _test_collector.receipts.clear()
        _test_mode = True
    pii_mod._receipt_hook = None
