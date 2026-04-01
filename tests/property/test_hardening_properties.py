# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Property-based tests for security hardening."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from provide.telemetry.logger.processors import harden_input
from provide.telemetry.pii import _detect_secret_in_value


@given(st.text(max_size=5000))
def test_output_values_always_bounded(text: str) -> None:
    """After harden_input, no string exceeds max_value_length."""
    processor = harden_input(100, 64, 8)
    result = processor(None, "", {"key": text})
    assert len(result["key"]) <= 100


@given(st.text(max_size=500))
def test_output_never_contains_control_chars(text: str) -> None:
    """After harden_input, no control chars remain (except \\n, \\t, \\r)."""
    processor = harden_input(1024, 64, 8)
    result = processor(None, "", {"key": text})
    for ch in result["key"]:
        code = ord(ch)
        if code < 0x20 or code == 0x7F:
            assert ch in ("\n", "\t", "\r")


@given(
    suffix=st.from_regex(r"[0-9A-Z]{16,80}", fullmatch=True),
)
def test_aws_key_patterns_always_detected(suffix: str) -> None:
    """Generated AWS-like keys are always detected."""
    text = "AKIA" + suffix
    assert _detect_secret_in_value(text) is True
