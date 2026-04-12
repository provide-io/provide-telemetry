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
