# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Regression tests for the PII secret-scan ReDoS input-length guard.

The secret detector previously ran the full regex battery over any string
shorter than 8 KiB up to an unbounded length.  We now short-circuit oversized
inputs to avoid catastrophic backtracking on adversarial payloads.
"""

from __future__ import annotations

import pytest

from provide.telemetry import pii as pii_mod
from provide.telemetry.pii import (
    _MAX_SECRET_SCAN_LENGTH,
    _detect_secret_in_value,
    sanitize_payload,
)


@pytest.fixture(autouse=True)
def _reset_rules() -> None:
    pii_mod.reset_pii_rules_for_tests()


# ---------------------------------------------------------------------------
# _detect_secret_in_value short-circuit
# ---------------------------------------------------------------------------


def test_oversize_value_short_circuits_even_with_embedded_secret() -> None:
    """A value longer than the cap is not scanned, even if it contains a secret."""
    # Real GitHub-token pattern, padded beyond the cap.
    token = "ghp_" + "A" * 36
    padding = "x" * (_MAX_SECRET_SCAN_LENGTH + 1)
    oversize = padding + token
    assert len(oversize) > _MAX_SECRET_SCAN_LENGTH
    assert _detect_secret_in_value(oversize) is False


def test_value_at_cap_is_still_scanned() -> None:
    """Values exactly at the cap (not over) continue to be scanned."""
    token = "ghp_" + "A" * 36
    # Build a payload whose length is exactly the cap and which ends with a
    # real secret pattern so the regex has something to match.
    prefix_len = _MAX_SECRET_SCAN_LENGTH - len(token)
    candidate = ("x" * prefix_len) + token
    assert len(candidate) == _MAX_SECRET_SCAN_LENGTH
    assert _detect_secret_in_value(candidate) is True


def test_normal_size_secret_still_detected() -> None:
    """Small, realistic secret-shaped strings still match."""
    token = "ghp_" + "A" * 36
    assert _detect_secret_in_value(token) is True


def test_short_value_below_min_length_skipped() -> None:
    """Pre-existing behaviour preserved: values below the min length short-circuit."""
    assert _detect_secret_in_value("abc") is False


# ---------------------------------------------------------------------------
# End-to-end: sanitize_payload honours the guard
# ---------------------------------------------------------------------------


def test_sanitize_payload_leaves_oversize_field_untouched() -> None:
    """An oversize field that merely contains a secret-shaped substring is
    not redacted because we never scan it.

    This is the documented trade-off: the ReDoS attack surface for multi-KB
    inputs is worse than the risk of a giant blob accidentally containing a
    secret — callers that care about that case should use explicit PIIRules.
    """
    token = "ghp_" + "A" * 36
    oversize = ("x" * (_MAX_SECRET_SCAN_LENGTH + 10)) + token
    payload = {"blob": oversize}
    result = sanitize_payload(payload, enabled=True)
    assert result["blob"] == oversize  # untouched
