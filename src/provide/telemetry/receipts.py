# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Cryptographic redaction receipts — strippable governance module.

When deleted, the receipt hook stays None and no receipts are generated.
"""

from __future__ import annotations

__all__ = [
    "RedactionReceipt",
    "enable_receipts",
    "get_emitted_receipts_for_tests",
]

import hashlib
import hmac as hmac_mod
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from provide.telemetry import pii as pii_mod

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RedactionReceipt:
    receipt_id: str
    timestamp: str
    service_name: str
    field_path: str
    action: str
    original_hash: str
    hmac: str


_lock = threading.Lock()
_enabled: bool = False
_signing_key: str | None = None
_service_name: str = "unknown"
_test_receipts: list[RedactionReceipt] = []
_test_mode: bool = False


def enable_receipts(
    enabled: bool = True,  # pragma: no mutate — all callers pass explicitly
    signing_key: str | None = None,
    service_name: str = "unknown",  # pragma: no mutate — all callers pass explicitly
) -> None:
    global _enabled, _signing_key, _service_name
    with _lock:
        _enabled = enabled  # pragma: no mutate
        _signing_key = signing_key
        _service_name = service_name
    if enabled:
        pii_mod._receipt_hook = _on_redaction
    else:
        pii_mod._receipt_hook = None


def _on_redaction(field_path: str, action: str, original_value: Any) -> None:
    receipt_id = str(uuid.uuid4())
    timestamp = datetime.now(tz=UTC).isoformat()
    original_hash = hashlib.sha256(str(original_value).encode("utf-8")).hexdigest()  # pragma: no mutate

    with _lock:
        key = _signing_key
        svc = _service_name
        in_test = _test_mode

    hmac_value = ""
    if key:
        payload = f"{receipt_id}|{timestamp}|{field_path}|{action}|{original_hash}"
        hmac_value = hmac_mod.new(
            key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()  # pragma: no mutate

    receipt = RedactionReceipt(
        receipt_id=receipt_id,
        timestamp=timestamp,
        service_name=svc,
        field_path=field_path,
        action=action,
        original_hash=original_hash,
        hmac=hmac_value,
    )

    if in_test:
        with _lock:
            _test_receipts.append(receipt)
    else:
        _logger.debug(
            "provide.pii.redaction_receipt",
            extra={"receipt_id": receipt.receipt_id, "field_path": receipt.field_path},
        )


def get_emitted_receipts_for_tests() -> list[RedactionReceipt]:
    with _lock:
        return list(_test_receipts)


def _reset_receipts_for_tests() -> None:
    global _enabled, _signing_key, _test_mode
    with _lock:
        _enabled = False  # pragma: no mutate
        _signing_key = None  # pragma: no mutate — "" is equivalent (both falsy for HMAC check)
        _test_receipts.clear()
        _test_mode = True
    pii_mod._receipt_hook = None
