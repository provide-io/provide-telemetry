# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The Python SDK against the canonical governance receipt vectors.

``spec/receipt_fixtures.yaml`` is the cross-language contract; reproducing it
byte for byte is what makes a Python receipt verifiable by a Go or TypeScript
consumer. ``tests/tooling/test_receipt_fixtures.py`` checks the fixture file
itself against ``rfc8785``; this file checks *us* against the fixture.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

import pytest
import rfc8785
import yaml

from provide.telemetry.receipts import canonical_json, receipt_payload, sign_receipt


def _find_fixtures() -> Path:
    """Locate spec/receipt_fixtures.yaml by walking up, not by counting parents.

    mutmut runs the suite against a copy of the tree under ``mutants/``, which
    has no ``spec/`` beside it, so a fixed ``parent.parent.parent`` resolves to
    a path that does not exist and the whole file errors during collection.
    Walking up until the fixture is found works from either location.

    This file deliberately stays in the mutation run rather than being marked
    ``tooling`` to dodge the problem: these vectors are the strongest pressure
    on canonical_json and sign_receipt, and excluding them would quietly hand
    those functions a free pass.
    """
    for candidate in Path(__file__).resolve().parents:
        fixtures = candidate / "spec" / "receipt_fixtures.yaml"
        if fixtures.is_file():
            return fixtures
    raise RuntimeError("spec/receipt_fixtures.yaml not found in any parent directory")


_FIXTURES = _find_fixtures()


def _cases() -> list[dict[str, Any]]:
    loaded: dict[str, Any] = yaml.safe_load(_FIXTURES.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = loaded["cases"]
    return cases


def _normalize(node: Any) -> Any:
    """Apply the contract's non-finite normalization to a fixture input."""
    if isinstance(node, float) and not math.isfinite(node):
        return None
    if isinstance(node, dict):
        return {key: _normalize(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_normalize(item) for item in node]
    return node


@pytest.mark.parametrize("case", _cases(), ids=lambda case: str(case["id"]))
def test_receipt_vector(case: dict[str, Any]) -> None:
    assert canonical_json(case["input"]) == case["canonical_json"]

    receipt = sign_receipt(
        case["input"],
        receipt_id=case["receipt_id"],
        timestamp=case["timestamp"],
        field_path=case["field_path"],
        action=case["action"],
        key=case["key"].encode(),
    )
    assert receipt.original_hash == case["original_hash"]
    assert receipt.hmac == case["signature"]
    assert (
        receipt_payload(
            receipt.receipt_id,
            receipt.timestamp,
            receipt.field_path,
            receipt.action,
            receipt.original_hash,
        )
        == case["payload"]
    )


@pytest.mark.parametrize("case", _cases(), ids=lambda case: str(case["id"]))
def test_normalization_is_the_only_difference_from_jcs(case: dict[str, Any]) -> None:
    """Our canonicalization agrees with an independent JCS implementation.

    Checking against ``rfc8785`` rather than only against the fixture is what
    stops a shared mistake: if the committed bytes were wrong, digests derived
    from them would still agree with them.
    """
    assert canonical_json(case["input"]) == rfc8785.dumps(_normalize(case["input"])).decode("utf-8")


def test_hash_distinguishes_a_number_from_its_string() -> None:
    """The reason the digest is over JCS and not over str(value)."""
    assert canonical_json(1) != canonical_json("1")
    number = sign_receipt(1, receipt_id="a", timestamp="t", field_path="f", action="redact")
    text = sign_receipt("1", receipt_id="a", timestamp="t", field_path="f", action="redact")
    assert number.original_hash != text.original_hash


def test_unsigned_receipt_has_an_empty_hmac() -> None:
    receipt = sign_receipt({}, receipt_id="a", timestamp="t", field_path="f", action="drop")
    assert receipt.hmac == ""
    assert receipt.service_name == "unknown"
    assert receipt.original_hash == hashlib.sha256(b"{}").hexdigest()
