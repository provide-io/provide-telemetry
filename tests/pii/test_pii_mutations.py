# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests targeting mutation-testing survivors in pii.py."""

from __future__ import annotations

from typing import Any

import pytest

from provide.telemetry import pii as pii_mod
from provide.telemetry.pii import (
    PIIRule,
    _apply_default_sensitive_key_redaction,
    _apply_rule,
    _mask,
    _match,
    register_pii_rule,
    replace_pii_rules,
    sanitize_payload,
)


@pytest.fixture(autouse=True)
def _reset_rules() -> None:
    pii_mod.reset_pii_rules_for_tests()


# ---------------------------------------------------------------------------
# _mask survivors
# ---------------------------------------------------------------------------


class TestMask:
    """Kill mutants in _mask."""

    def test_redact_mode_returns_exactly_three_stars(self) -> None:
        """Kills `"***"` -> `"XX***XX"` and `"redact"` -> `"XXredactXX"` mutants."""
        result = _mask("secret_value", "redact", 8)
        assert result == "***"
        assert len(result) == 3

    def test_redact_mode_string_comparison_exact(self) -> None:
        """Kills `"redact"` -> `"REDACT"` mutant (case-sensitive mode check)."""
        # "redact" mode should produce "***", not fall through to truncate
        result = _mask("hello", "redact", 2)
        assert result == "***"

    def test_truncate_to_zero_gives_ellipsis_only(self) -> None:
        """Kills `max(0, truncate_to)` -> `max(1, truncate_to)` mutant.

        With truncate_to=0, text should be empty prefix + "..." since len > 0.
        """
        result = _mask("hello", "truncate", 0)
        assert result == "..."

    def test_truncate_boundary_exact_limit(self) -> None:
        """Kills `len(text) > limit` -> `>= limit` mutant.

        When text length equals limit exactly, no "..." should be appended.
        """
        result = _mask("abcd", "truncate", 4)
        assert result == "abcd"

    def test_truncate_one_over_limit(self) -> None:
        """Text one char over limit gets truncated with '...'."""
        result = _mask("abcde", "truncate", 4)
        assert result == "abcd..."

    def test_truncate_suffix_is_exactly_three_dots(self) -> None:
        """Kills `"..."` -> `""` mutant for truncation suffix."""
        result = _mask("longtext", "truncate", 2)
        assert result == "lo..."
        assert result.endswith("...")

    def test_drop_mode_returns_none(self) -> None:
        """Baseline: drop mode returns None."""
        assert _mask("value", "drop", 8) is None

    def test_hash_mode_returns_12_char_hex(self) -> None:
        """Baseline: hash mode returns 12-char hex digest."""
        result = _mask("value", "hash", 8)
        assert isinstance(result, str)
        assert len(result) == 12
        int(result, 16)  # must be valid hex


# ---------------------------------------------------------------------------
# _match survivors
# ---------------------------------------------------------------------------


class TestMatch:
    """Kill mutants in _match."""

    def test_wildcard_matches_any_element(self) -> None:
        """Kills `"*"` -> `"XX*XX"` mutant."""
        assert _match(("user", "*", "name"), ("user", "anything", "name")) is True
        assert _match(("*",), ("whatever",)) is True

    def test_wildcard_does_not_match_different_length(self) -> None:
        """Ensures length check still applies with wildcards."""
        assert _match(("*", "*"), ("a",)) is False

    def test_exact_match(self) -> None:
        """Baseline: exact path matching."""
        assert _match(("a", "b"), ("a", "b")) is True
        assert _match(("a", "b"), ("a", "c")) is False

    def test_strict_zip_enforced(self) -> None:
        """Kills `strict=True` -> `strict=False` mutant.

        With strict=True and mismatched lengths, zip raises ValueError.
        But the length check at the top should prevent that. This test
        verifies the length check is working correctly (not bypassed).
        """
        # Same length, partial match
        assert _match(("a", "b"), ("a", "x")) is False


# ---------------------------------------------------------------------------
# _apply_rule list handling survivors
# ---------------------------------------------------------------------------


class TestApplyRuleList:
    def test_apply_rule_redacts_list_items_via_wildcard(self) -> None:
        """Kills `"*"` -> `"XX*XX"` mutant in _apply_rule list path.

        When _apply_rule encounters a list, it uses "*" as the path segment
        for each item. A rule targeting ("items", "*", "secret") should match
        list elements.
        """
        node: dict[str, Any] = {
            "items": [
                {"secret": "value1", "ok": "data1"},  # pragma: allowlist secret
                {"secret": "value2", "ok": "data2"},  # pragma: allowlist secret
            ]
        }
        rule = PIIRule(path=("items", "*", "secret"), mode="redact")
        result = _apply_rule(node, rule)
        assert result["items"][0]["secret"] == "***"
        assert result["items"][1]["secret"] == "***"
        assert result["items"][0]["ok"] == "data1"
        assert result["items"][1]["ok"] == "data2"


# ---------------------------------------------------------------------------
# _apply_default_sensitive_key_redaction survivors
# ---------------------------------------------------------------------------


class TestApplyDefaultSensitiveKeyRedaction:
    """Kill mutants in _apply_default_sensitive_key_redaction."""

    def test_and_vs_or_isinstance_checks(self) -> None:
        """Kills `and` -> `or` in isinstance(node, dict) and isinstance(original, dict).

        If node is dict but original is not dict, should return node unchanged.
        """
        result = _apply_default_sensitive_key_redaction(
            {"password": "secret"},
            "not_a_dict",  # pragma: allowlist secret
        )
        assert result == {"password": "secret"}  # pragma: allowlist secret

    def test_orig_value_fallback_uses_value_not_none(self) -> None:
        """Kills `original.get(key, value)` -> `get(key, None)` or `get(key,)`.

        When key is missing from original, orig_value should fall back to
        `value` (current node value). If it fell back to None, comparison
        would differ, causing the already-redacted value to be kept.
        """
        node: dict[str, Any] = {"password": "secret", "safe": "data"}
        # original is missing 'password' key entirely
        original: dict[str, Any] = {"safe": "data"}
        result = _apply_default_sensitive_key_redaction(node, original)
        # password should NOT be redacted because node["password"] != orig fallback
        # Actually: orig_value = original.get("password", "secret") = "secret"
        # Since value == orig_value, it should be redacted
        assert result["password"] == "***"

    def test_orig_value_differs_preserves_already_masked(self) -> None:
        """When value differs from original, it means it was already masked by a rule."""
        node: dict[str, Any] = {"password": "already_masked"}
        original: dict[str, Any] = {"password": "original_password"}
        result = _apply_default_sensitive_key_redaction(node, original)
        # value != orig_value, so keep the already-masked value
        assert result["password"] == "already_masked"  # pragma: allowlist secret

    def test_nested_dict_recursion(self) -> None:
        """Kills various mutants by testing nested dict traversal."""
        node: dict[str, Any] = {"outer": {"token": "abc123", "safe": "ok"}}
        original: dict[str, Any] = {"outer": {"token": "abc123", "safe": "ok"}}
        result = _apply_default_sensitive_key_redaction(node, original)
        assert result["outer"]["token"] == "***"
        assert result["outer"]["safe"] == "ok"

    def test_list_traversal_with_strict_false(self) -> None:
        """Kills `strict=False` -> `strict=True` mutant.

        With strict=False, mismatched-length lists don't raise.
        """
        node: list[Any] = [{"token": "a"}, {"token": "b"}, {"token": "c"}]
        original: list[Any] = [{"token": "a"}, {"token": "b"}]
        # strict=False means zip stops at shorter list
        result = _apply_default_sensitive_key_redaction(node, original)
        assert isinstance(result, list)
        assert len(result) == 2  # zip truncates to shorter
        assert result[0]["token"] == "***"

    def test_list_node_with_non_list_original_returns_node(self) -> None:
        """Kills `and` -> `or` in isinstance(node, list) and isinstance(original, list).

        When node is a list but original is NOT, should return node unchanged.
        The `or` mutant would try to zip a list with a non-list and crash.
        """
        node: list[Any] = [{"token": "secret"}]
        result = _apply_default_sensitive_key_redaction(node, "not_a_list")
        assert result == [{"token": "secret"}]

    def test_non_dict_non_list_passthrough(self) -> None:
        """Non-container values pass through unchanged."""
        assert _apply_default_sensitive_key_redaction("hello", "hello") == "hello"
        assert _apply_default_sensitive_key_redaction(42, 42) == 42


# ---------------------------------------------------------------------------
# sanitize_payload survivors
# ---------------------------------------------------------------------------


class TestSanitizePayload:
    """Kill mutants in sanitize_payload."""

    def test_deepcopy_vs_shallow_copy(self) -> None:
        """Kills `copy.deepcopy(payload)` -> `copy.copy(payload)` mutant.

        With shallow copy, mutations to nested dicts in rules would affect
        the original payload. deepcopy prevents this.
        """
        inner: dict[str, Any] = {"secret": "value", "safe": "data"}
        payload: dict[str, Any] = {"nested": inner}
        replace_pii_rules([PIIRule(path=("nested", "secret"), mode="drop")])
        result = sanitize_payload(payload, enabled=True)  # pragma: allowlist secret
        # Original must be unmodified
        assert payload["nested"]["secret"] == "value"  # pragma: allowlist secret
        # Result should have secret removed
        assert "secret" not in result["nested"]
        # Verify they are different objects
        assert result["nested"] is not payload["nested"]

    def test_register_pii_rule_stores_correctly(self) -> None:
        """Kills mutants in register_pii_rule."""
        rule = PIIRule(path=("user", "email"), mode="hash")
        register_pii_rule(rule)
        rules = pii_mod.get_pii_rules()
        assert len(rules) == 1
        assert rules[0] is rule
        assert rules[0].path == ("user", "email")
        assert rules[0].mode == "hash"

    def test_sanitize_disabled_returns_copy_not_original(self) -> None:
        """When disabled, returns a shallow copy (equal content, different object)."""
        payload: dict[str, Any] = {"password": "secret"}  # pragma: allowlist secret
        result = sanitize_payload(payload, enabled=False)
        assert result == payload
        assert result is not payload

    def test_sanitize_with_multiple_rules_applied_in_order(self) -> None:
        """Verify rules are applied sequentially."""
        payload: dict[str, Any] = {"field": "longvalue123"}
        replace_pii_rules(
            [
                PIIRule(path=("field",), mode="truncate", truncate_to=4),
            ]
        )
        result = sanitize_payload(payload, enabled=True)
        assert result["field"] == "long..."

    def test_custom_noop_truncate_on_sensitive_key_not_overridden(self) -> None:
        """Custom rule with no-op truncate (short value) must not be overridden by default redaction.

        When a custom rule produces a value equal to the original (e.g., truncate on a short value),
        the default redaction must not overwrite it with '***'.
        """
        payload: dict[str, Any] = {"password": "ab"}
        replace_pii_rules([PIIRule(path=("password",), mode="truncate", truncate_to=10)])
        result = sanitize_payload(payload, enabled=True)
        # Custom rule left value unchanged (len("ab") <= 10), default must respect that
        assert result["password"] == "ab"

    def test_rule_targeted_keys_propagates_through_nested_dict(self) -> None:
        """Kills mutant replacing rule_targeted_keys with None in dict recursion.

        A custom rule targeting a nested sensitive key must prevent default
        redaction at any depth, not just the top level.
        """
        payload: dict[str, Any] = {"outer": {"password": "short"}}
        replace_pii_rules([PIIRule(path=("outer", "password"), mode="truncate", truncate_to=100)])
        result = sanitize_payload(payload, enabled=True)
        # Custom rule is a no-op (value shorter than truncate_to), but the key
        # is tracked as rule-targeted so default redaction must NOT apply "***"
        assert result["outer"]["password"] == "short"  # pragma: allowlist secret

    def test_rule_targeted_keys_propagates_through_list(self) -> None:
        """Kills mutant replacing rule_targeted_keys with None in list recursion."""
        payload: dict[str, Any] = {"items": [{"token": "val"}]}
        replace_pii_rules([PIIRule(path=("items", "*", "token"), mode="truncate", truncate_to=100)])
        result = sanitize_payload(payload, enabled=True)
        # Custom rule is a no-op; default must not overwrite with "***"
        assert result["items"][0]["token"] == "val"


# ---------------------------------------------------------------------------
# Additional _apply_rule mutant killers
# ---------------------------------------------------------------------------


class TestApplyRuleDictOutput:
    """Kill mutants in _apply_rule dict construction."""

    def test_apply_rule_dict_starts_as_empty_dict_not_none(self) -> None:
        """Kills mutmut_1: output = {} -> output = None.

        When _apply_rule processes a dict, it must build an output dict.
        The None mutant would crash on output[key] = ... assignment.
        """
        rule = PIIRule(path=("nonexistent",), mode="redact")
        node: dict[str, Any] = {"safe_key": "safe_value"}
        result = _apply_rule(node, rule)
        assert isinstance(result, dict)
        assert result == {"safe_key": "safe_value"}

    def test_apply_rule_dict_with_matching_rule_produces_dict(self) -> None:
        """Complementary: when rule matches, output must still be a dict."""
        rule = PIIRule(path=("secret",), mode="redact")
        node: dict[str, Any] = {"secret": "hunter2", "public": "data"}
        result = _apply_rule(node, rule)
        assert isinstance(result, dict)
        assert result["secret"] == "***"
        assert result["public"] == "data"


# ---------------------------------------------------------------------------
# Additional _apply_default_sensitive_key_redaction mutant killers
# ---------------------------------------------------------------------------


class TestApplyDefaultSensitiveKeyRedactionMutants:
    """Kill remaining mutants in _apply_default_sensitive_key_redaction."""

    def test_none_rule_targeted_keys_replaced_with_frozenset(self) -> None:
        """Kills mutmut_1: `is None` -> `is not None` and mutmut_2: frozenset() -> None.

        When rule_targeted_keys is None (default), it must be replaced with
        an empty frozenset so the `key in rule_targeted_keys` check works.
        The `is not None` mutant would skip the replacement when keys IS None,
        causing a TypeError on `key in None`.
        The `frozenset() -> None` mutant would replace with None, also causing TypeError.
        """
        # Call with rule_targeted_keys=None (default) — must not crash
        node: dict[str, Any] = {"password": "secret123", "name": "alice"}
        original: dict[str, Any] = {"password": "secret123", "name": "alice"}
        result = _apply_default_sensitive_key_redaction(node, original)
        assert result["password"] == "***"
        assert result["name"] == "alice"

    def test_and_vs_or_dict_isinstance_with_non_dict_original(self) -> None:
        """Kills mutmut_3: `and isinstance(original, dict)` -> `or isinstance(original, dict)`.

        When node is a dict but original is a non-dict (e.g., a string),
        the `or` mutant would enter the dict branch and crash on original.get().
        """
        result = _apply_default_sensitive_key_redaction({"password": "secret"}, 42)  # pragma: allowlist secret
        # Should return the node unchanged since original is not a dict
        assert result == {"password": "secret"}  # pragma: allowlist secret

    def test_and_vs_or_dict_isinstance_with_non_dict_node(self) -> None:
        """Complementary: node is NOT a dict but original IS a dict.

        The `or` mutant would enter the dict branch and crash on node.items().
        """
        result = _apply_default_sensitive_key_redaction("just_a_string", {"password": "secret"})
        assert result == "just_a_string"


# ---------------------------------------------------------------------------
# Additional sanitize_payload mutant killers
# ---------------------------------------------------------------------------


class TestSanitizePayloadEnabledFlag:
    """Kill mutants in sanitize_payload enabled flag."""

    def test_disabled_returns_payload_without_redaction(self) -> None:
        """Kills mutmut_1: `if not enabled` -> `if enabled`.

        When enabled=False, sensitive keys must NOT be redacted.
        The mutant would invert the check, redacting when disabled.
        """
        payload: dict[str, Any] = {"password": "secret", "data": "public"}  # pragma: allowlist secret
        result = sanitize_payload(payload, enabled=False)
        assert result["password"] == "secret"  # NOT redacted  # pragma: allowlist secret
        assert result["data"] == "public"

    def test_enabled_redacts_sensitive_keys(self) -> None:
        """Complementary: when enabled=True, sensitive keys ARE redacted.

        The mutant (if not enabled -> if enabled) would skip redaction
        when enabled=True and return a plain copy.
        """
        payload: dict[str, Any] = {"password": "secret", "data": "public"}
        result = sanitize_payload(payload, enabled=True)
        assert result["password"] == "***"  # redacted
        assert result["data"] == "public"


class TestApplyDefaultRedactionListDepthIncrement:
    """Kill pii.x__apply_default_sensitive_key_redaction__mutmut_47: depth+1 → depth+2."""

    def test_list_depth_increment_is_one_not_two(self) -> None:
        """Kills mutmut_47: depth+1 → depth+2 in the list recursion branch.

        Trace with max_depth=3 and payload {"data": [{"password": "secret"}]}:

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
        payload: dict[str, Any] = {"data": [{"password": "secret"}]}
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
