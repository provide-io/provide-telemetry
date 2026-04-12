# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests targeting depth-related mutation survivors in pii.py.

Split from test_pii_mutations.py to stay under the 500 LOC per file limit.
Covers _apply_rule depth-limit behaviour and _apply_default_sensitive_key_redaction
boundary conditions.
"""

from __future__ import annotations

from typing import Any

import pytest

from provide.telemetry import pii as pii_mod
from provide.telemetry.pii import (
    PIIRule,
    _apply_default_sensitive_key_redaction,
    _apply_rule,
    replace_pii_rules,
    sanitize_payload,
)


@pytest.fixture(autouse=True)
def _reset_rules() -> None:
    pii_mod.reset_pii_rules_for_tests()


class TestApplyDefaultRedactionListDepthIncrement:
    """Kill pii.x__apply_default_sensitive_key_redaction__mutmut_47: depth+1 → depth+2."""

    def test_list_depth_increment_is_one_not_two(self) -> None:
        """Kills mutmut_47: depth+1 → depth+2 in the list recursion branch.

        Trace with max_depth=3 and payload {"data": [{"pin": "1234"}]}:

        Original (depth+1):
          depth=0: outer dict → "data" value (list) → call list at depth=0+1=1
          depth=1: list → call items at depth=1+1=2
          depth=2 < 3: process dict → "password" → redact → "***" ✓

        Mutation (depth+2):
          depth=0: outer dict → "data" value (list) → call list at depth=0+1=1
          depth=1: list → call items at depth=1+2=3
          depth=3 >= 3: return node unchanged → "secret" ✗
        """
        replace_pii_rules([])
        payload: dict[str, Any] = {"data": [{"password": "secret"}]}  # pragma: allowlist secret
        result = sanitize_payload(payload, enabled=True, max_depth=3)
        # With original depth+1, password inside the list is processed and redacted
        assert result["data"][0]["password"] == "***"


class TestApplyRuleMutants:
    def test_depth_32_returns_node_unchanged(self) -> None:
        rule = PIIRule(path=("password",), mode="redact")
        node: dict[str, Any] = {"password": "secret"}  # pragma: allowlist secret
        result = _apply_rule(node, rule, depth=32)
        assert result is node

    def test_redact_mode_value_in_output(self) -> None:
        rule = PIIRule(path=("password",), mode="redact")
        result = _apply_rule({"password": "secret"}, rule)  # pragma: allowlist secret
        assert result["password"] == "***"

    def test_dict_recursion_depth_30(self) -> None:
        rule = PIIRule(path=("inner", "password"), mode="redact")
        node: dict[str, Any] = {"inner": {"password": "secret"}}  # pragma: allowlist secret
        result = _apply_rule(node, rule, depth=30)
        assert result["inner"]["password"] == "***"

    def test_depth_31_stops_dict_recursion(self) -> None:
        # depth=31 → child recurses at 32 → hits limit; kills mutmut_27/28
        rule = PIIRule(path=("inner", "password"), mode="redact")
        node: dict[str, Any] = {"inner": {"password": "secret"}}  # pragma: allowlist secret
        result = _apply_rule(node, rule, depth=31)
        assert result["inner"]["password"] == "secret"  # pragma: allowlist secret


class TestApplyDefaultRedactionBoundaries:
    def test_depth_at_max_returns_unchanged(self) -> None:
        node: dict[str, Any] = {"password": "secret"}  # pragma: allowlist secret
        result = _apply_default_sensitive_key_redaction(node, node, depth=1, max_depth=1)
        assert result["password"] == "secret"  # pragma: allowlist secret

    def test_none_rule_targeted_keys(self) -> None:
        node: dict[str, Any] = {"password": "secret"}  # pragma: allowlist secret
        result = _apply_default_sensitive_key_redaction(node, node, rule_targeted_keys=None)
        assert result["password"] == "***"

    def test_dict_recursion_depth_1_max_3(self) -> None:
        node: dict[str, Any] = {"outer": {"password": "secret"}}  # pragma: allowlist secret
        result = _apply_default_sensitive_key_redaction(node, node, depth=1, max_depth=3)
        assert result["outer"]["password"] == "***"

    def test_list_recursion_hits_depth_limit(self) -> None:
        # depth=31 → list item at 32 → hits limit; kills mutmut_44/46
        items = [{"password": "secret"}]  # pragma: allowlist secret
        result = _apply_default_sensitive_key_redaction(items, items, depth=31, max_depth=32)
        assert result[0]["password"] == "secret"  # pragma: allowlist secret

    def test_list_recursion_forwards_max_depth(self) -> None:
        # max_depth=2 forwarded → item at depth=2 hits limit; kills mutmut_45
        items = [{"password": "secret"}]  # pragma: allowlist secret
        result = _apply_default_sensitive_key_redaction(items, items, depth=1, max_depth=2)
        assert result[0]["password"] == "secret"  # pragma: allowlist secret


# ---------------------------------------------------------------------------
# receipt_hook argument tests for list-item secret detection
# Kills mutmut_59, 61, 65, 66, 75, 81
# ---------------------------------------------------------------------------

# A value long enough to match the long_hex secret pattern (40+ hex chars).
_HEX_SECRET = "a" * 40  # pragma: allowlist secret


class TestListItemReceiptHookArguments:
    """Kills mutmut_59/61/65/66: exact arguments passed to receipt_hook for list item secrets."""

    def test_receipt_hook_list_item_key_is_list_item_literal(self) -> None:
        """Kill mutmut_59 (key→None) and mutmut_65/66 (key string mutations).

        When a secret is detected in a list item string, the receipt_hook
        must be called with the exact key literal '(list_item)' — not None,
        not 'XX(list_item)XX', not '(LIST_ITEM)'.
        """
        calls: list[tuple[object, str, object]] = []

        def hook(key: object, mode: str, value: object) -> None:
            calls.append((key, mode, value))

        _apply_default_sensitive_key_redaction([_HEX_SECRET], [_HEX_SECRET], receipt_hook=hook)
        assert len(calls) == 1, "receipt_hook must be called exactly once for one list-item secret"
        assert calls[0][0] == "(list_item)", f"expected key '(list_item)', got {calls[0][0]!r}"

    def test_receipt_hook_list_item_value_is_original_item(self) -> None:
        """Kill mutmut_61: third argument (value) must be the original item, not None."""
        calls: list[tuple[object, str, object]] = []

        def hook(key: object, mode: str, value: object) -> None:
            calls.append((key, mode, value))

        _apply_default_sensitive_key_redaction([_HEX_SECRET], [_HEX_SECRET], receipt_hook=hook)
        assert len(calls) == 1
        assert calls[0][2] == _HEX_SECRET, f"expected value to be the original secret string, got {calls[0][2]!r}"

    def test_receipt_hook_list_item_mode_is_redact(self) -> None:
        """Verify the mode argument is 'redact' (sanity check for the hook call)."""
        calls: list[tuple[object, str, object]] = []

        def hook(key: object, mode: str, value: object) -> None:
            calls.append((key, mode, value))

        _apply_default_sensitive_key_redaction([_HEX_SECRET], [_HEX_SECRET], receipt_hook=hook)
        assert len(calls) == 1
        assert calls[0][1] == "redact"


class TestListItemReceiptHookPropagatedToNestedItems:
    """Kills mutmut_75 (receipt_hook=None) and mutmut_81 (receipt_hook removed)
    in the recursive call for non-secret list items.

    When a list item is NOT itself a secret string, the function recurses into
    it. The receipt_hook must be forwarded to that recursive call.
    """

    def test_receipt_hook_forwarded_to_nested_dict_in_list(self) -> None:
        """Kill mutmut_75/81: hook must reach a sensitive key nested inside a list item dict."""
        calls: list[tuple[object, str, object]] = []

        def hook(key: object, mode: str, value: object) -> None:
            calls.append((key, mode, value))

        # List item is a dict (not a secret string itself), so the else branch recurses.
        # The nested dict has a sensitive key 'token' that default redaction should catch.
        node = [{"token": "some_value"}]
        original = [{"token": "some_value"}]
        _apply_default_sensitive_key_redaction(node, original, receipt_hook=hook)
        assert len(calls) == 1, "receipt_hook must be forwarded into recursion for non-secret list items"
        assert calls[0][0] == "token"
        assert calls[0][1] == "redact"
