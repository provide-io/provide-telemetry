# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Self-tests for the canonical governance receipt and pipeline vectors.

These fixtures are the cross-language contract: every SDK must reproduce the
same canonical JSON bytes, the same SHA-256 of them, and the same HMAC over the
same pipe-joined payload. A fixture that is only self-consistent is worthless —
if the committed `canonical_json` were wrong, digests derived *from* it would
still agree with it, and all five SDKs would be forced to reproduce the same
wrong bytes. So the canonical string is checked against `rfc8785`, an
independent RFC 8785 implementation, rather than against the expression that
produced it. Python's `json.dumps` cannot serve here: it emits "-0.0" where JCS
requires "0".
"""

from __future__ import annotations

import hashlib
import hmac
import math
from pathlib import Path
from typing import Any

import pytest
import rfc8785
import yaml

pytestmark = pytest.mark.tooling

_REPO_ROOT = Path(__file__).parent.parent.parent
_RECEIPTS = _REPO_ROOT / "spec" / "receipt_fixtures.yaml"
_PIPELINE = _REPO_ROOT / "spec" / "pipeline_fixtures.yaml"

# The canonical pipeline stages, in the order every SDK must run them.
_CANONICAL_EVENTS = [
    "consent",
    "sampling",
    "backpressure",
    "hardening",
    "pii",
    "receipt",
    "local",
    "backend",
    "health",
    "release",
]


def _load(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded


def _receipt_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = _load(_RECEIPTS)["cases"]
    return cases


def test_receipt_vectors_are_self_consistent() -> None:
    for case in _receipt_cases():
        cid = case["id"]
        # The canonical string, verified against an independent JCS implementation.
        expected_canonical = rfc8785.dumps(case["normalized"]).decode("utf-8")
        assert expected_canonical == case["canonical_json"], cid

        assert hashlib.sha256(case["canonical_json"].encode()).hexdigest() == case["original_hash"], cid
        assert (
            hmac.new(case["key"].encode(), case["payload"].encode(), hashlib.sha256).hexdigest() == case["signature"]
        ), cid
        assert case["payload"] == "|".join(
            [
                case["receipt_id"],
                case["timestamp"],
                case["field_path"],
                case["action"],
                case["original_hash"],
            ]
        ), cid


def test_receipt_digests_are_lowercase_hex() -> None:
    for case in _receipt_cases():
        for field in ("original_hash", "signature"):
            value = case[field]
            assert value == value.lower(), f"{case['id']}: {field} must be lowercase"
            assert len(value) == 64, f"{case['id']}: {field} must be 64 hex chars"
            assert set(value) <= set("0123456789abcdef"), f"{case['id']}: {field} must be hex"


def test_receipt_case_ids_are_unique() -> None:
    ids = [case["id"] for case in _receipt_cases()]
    assert len(ids) == len(set(ids)), f"duplicate case ids: {ids}"


def test_normalization_removes_non_finite_numbers() -> None:
    """JCS has no encoding for NaN or Infinity, so SDKs must normalize first.

    The fixture carries both the raw `input` and the `normalized` form precisely
    so the normalization step is part of the contract rather than left to each
    SDK to invent.
    """
    covered = False
    for case in _receipt_cases():
        if "input" not in case:
            continue
        if _has_non_finite(case["input"]):
            covered = True
            assert not _has_non_finite(case["normalized"]), (
                f"{case['id']}: normalized form still contains a non-finite number"
            )
            # rfc8785 rejects non-finite input; a normalized form it accepts is
            # the proof that normalization actually happened.
            rfc8785.dumps(case["normalized"])
    assert covered, "no fixture case exercises non-finite normalization"


def _has_non_finite(node: Any) -> bool:
    if isinstance(node, float):
        return math.isnan(node) or math.isinf(node)
    if isinstance(node, dict):
        return any(_has_non_finite(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_non_finite(v) for v in node)
    return False


def test_pipeline_vectors_release_once_and_preserve_prefix_order() -> None:
    data = _load(_PIPELINE)
    canonical = data["events"]
    assert canonical == _CANONICAL_EVENTS
    for case in data["cases"]:
        cid = case["id"]
        assert case["expected"].count("release") == 1, cid
        # Every exit path must be a subsequence of the canonical order: a stage
        # may be skipped, but two stages may never swap places.
        assert [event for event in canonical if event in case["expected"]] == case["expected"], cid


def test_pipeline_cases_cover_every_exit_path() -> None:
    data = _load(_PIPELINE)
    ids = {case["id"] for case in data["cases"]}
    required = {
        "consent_rejection",
        "sampling_rejection",
        "queue_rejection",
        "local_only_success",
        "backend_success",
        "backend_failure",
    }
    assert required <= ids, f"missing exit cases: {sorted(required - ids)}"


def test_pipeline_rejections_stop_before_backend() -> None:
    """A rejected event must never reach the backend, but must still release."""
    for case in _load(_PIPELINE)["cases"]:
        if not case["id"].endswith("_rejection"):
            continue
        assert "backend" not in case["expected"], case["id"]
        assert case["expected"][-1] == "release", case["id"]
