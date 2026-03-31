# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Tests for security hardening: input poisoning, secret detection, protocol resilience."""

from __future__ import annotations

from typing import Any

import pytest

from undef.telemetry import pii as pii_mod
from undef.telemetry import propagation as propagation_mod
from undef.telemetry.config import SecurityConfig, TelemetryConfig
from undef.telemetry.exceptions import ConfigurationError
from undef.telemetry.logger.processors import harden_input, sanitize_sensitive_fields
from undef.telemetry.pii import _detect_secret_in_value, sanitize_payload


@pytest.fixture(autouse=True)
def _reset_pii() -> None:
    pii_mod.reset_pii_rules_for_tests()


# ---------------------------------------------------------------------------
# TestHardenInputProcessor
# ---------------------------------------------------------------------------


class TestHardenInputProcessor:
    """Test the harden_input processor from processors.py."""

    def test_truncates_string_values_at_max_value_length(self) -> None:
        processor = harden_input(10, 64, 8)
        result = processor(None, "", {"key": "a" * 50})
        assert result["key"] == "a" * 10

    def test_strips_null_bytes(self) -> None:
        processor = harden_input(1024, 64, 8)
        result = processor(None, "", {"key": "hello\x00world"})
        assert result["key"] == "helloworld"

    def test_strips_control_characters(self) -> None:
        processor = harden_input(1024, 64, 8)
        # \x01-\x08, \x0b, \x0c, \x0e-\x1f, \x7f
        dirty = "a\x01b\x08c\x0bd\x0ce\x0ef\x1fg\x7fh"
        result = processor(None, "", {"key": dirty})
        assert result["key"] == "abcdefgh"

    def test_preserves_newline_tab_carriage_return(self) -> None:
        processor = harden_input(1024, 64, 8)
        text = "line1\nline2\ttab\rcarriage"
        result = processor(None, "", {"key": text})
        assert result["key"] == text

    def test_limits_attribute_count(self) -> None:
        processor = harden_input(1024, 3, 8)
        event_dict = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
        result = processor(None, "", event_dict)
        assert len(result) == 3
        # First 3 keys preserved
        keys = list(result.keys())
        assert keys == ["a", "b", "c"]

    def test_caps_nesting_depth(self) -> None:
        processor = harden_input(1024, 64, 1)
        deep = {"level1": {"level2": {"level3": "deep_value\x00evil"}}}
        result = processor(None, "", deep)
        # depth=0 processes level1 (dict at depth < 1 -> recurse)
        # depth=1 processes level2 (dict at depth NOT < 1 -> returned as-is)
        assert result["level1"] == {"level2": {"level3": "deep_value\x00evil"}}

    def test_non_string_values_pass_through(self) -> None:
        processor = harden_input(1024, 64, 8)
        result = processor(None, "", {"i": 42, "f": 3.14, "b": True, "n": None})
        assert result == {"i": 42, "f": 3.14, "b": True, "n": None}

    def test_empty_dict_passes_through(self) -> None:
        processor = harden_input(1024, 64, 8)
        result = processor(None, "", {})
        assert result == {}

    def test_list_values_cleaned_recursively(self) -> None:
        processor = harden_input(1024, 64, 8)
        result = processor(None, "", {"items": ["hello\x00", "clean"]})
        assert result["items"] == ["hello", "clean"]

    def test_truncation_applied_after_control_char_stripping(self) -> None:
        processor = harden_input(5, 64, 8)
        # 3 clean chars + 2 control chars + 5 clean chars = 10 total, 8 after strip
        result = processor(None, "", {"key": "abc\x00\x01defgh"})
        # After strip: "abcdefgh" (8 chars), truncated to 5
        assert result["key"] == "abcde"

    def test_control_char_sub_replacement_is_empty(self) -> None:
        """Kills mutant replacing sub("", value) -> sub("X", value) or similar.

        Control chars must be stripped (replaced with nothing), not substituted.
        """
        processor = harden_input(1024, 64, 8)
        result = processor(None, "", {"key": "a\x01b"})
        assert result["key"] == "ab"
        assert len(result["key"]) == 2  # exactly 2 chars, no replacements

    def test_string_at_exact_max_length_not_truncated(self) -> None:
        """Kills: len(cleaned) > max_value_length -> >= boundary mutation.

        A string exactly at the limit must NOT be truncated.
        """
        processor = harden_input(10, 64, 8)
        result = processor(None, "", {"key": "a" * 10})
        assert result["key"] == "a" * 10
        assert len(result["key"]) == 10

    def test_string_one_over_max_is_truncated(self) -> None:
        """Complement: string one over the limit IS truncated."""
        processor = harden_input(10, 64, 8)
        result = processor(None, "", {"key": "a" * 11})
        assert result["key"] == "a" * 10
        assert len(result["key"]) == 10

    def test_dict_at_max_depth_not_recursed(self) -> None:
        """Kills: depth < max_depth -> depth <= max_depth boundary mutation for dicts.

        At depth == max_depth, nested dicts should be returned as-is (no cleaning).
        _processor calls _clean_value(v, 0), so first dict recurse is depth 0 < max.
        With max_depth=1: depth 0 < 1 recurses, depth 1 NOT < 1 returns as-is.
        """
        processor = harden_input(1024, 64, 1)
        deep = {"a": {"b": "dirty\x01value"}}
        result = processor(None, "", deep)
        # _processor: _clean_value({"b": ...}, 0) -> dict at 0 < 1, recurse
        # _clean_value("dirty...", 1) -> str, cleaned at any depth
        assert result["a"]["b"] == "dirtyvalue"

        # Now with max_depth=0: dict at depth 0 NOT < 0, returned as-is
        processor0 = harden_input(1024, 64, 0)
        result0 = processor0(None, "", {"a": {"b": "dirty\x01value"}})
        # The dict value at depth 0 is not recursed, returned as-is
        assert result0["a"] == {"b": "dirty\x01value"}

    def test_dict_just_below_max_depth_is_recursed(self) -> None:
        """Complement: at depth < max_depth, dicts ARE recursed."""
        processor = harden_input(1024, 64, 1)
        data = {"a": "dirty\x01value"}
        result = processor(None, "", data)
        # depth 0 < 1: string value cleaned
        assert result["a"] == "dirtyvalue"

    def test_list_at_max_depth_not_recursed(self) -> None:
        """Kills: depth < max_depth -> depth <= max_depth for lists.

        At depth == max_depth, nested lists should be returned as-is.
        """
        processor = harden_input(1024, 64, 1)
        data = {"items": ["dirty\x01value"]}
        result = processor(None, "", data)
        # depth 0: process outer dict, items is a list at depth 0 < 1: recurse
        # each list item at depth 1: strings cleaned
        assert result["items"] == ["dirtyvalue"]

        # Now with max_depth=0: list at depth 0 NOT < 0, returned as-is
        processor0 = harden_input(1024, 64, 0)
        result0 = processor0(None, "", {"items": ["dirty\x01value"]})
        assert result0["items"] == ["dirty\x01value"]

    def test_depth_increment_in_dict_recursion(self) -> None:
        """Kills: depth + 1 -> depth + 2 or depth - 1 in dict recursion.

        With max_depth=3, we should be able to clean strings at depth 2.
        If depth increments by 2, depth 1 -> 3 skips cleaning at depth 2.
        """
        processor = harden_input(1024, 64, 3)
        data = {"a": {"b": {"c": "val\x01ue"}}}
        result = processor(None, "", data)
        # depth 0 -> 1 -> 2: all < 3, so c's value is cleaned
        assert result["a"]["b"]["c"] == "value"

    def test_depth_increment_in_list_recursion(self) -> None:
        """Kills: depth + 1 -> depth + 2 or depth - 1 in list recursion."""
        processor = harden_input(1024, 64, 3)
        data = {"items": [{"nested": "val\x01ue"}]}
        result = processor(None, "", data)
        assert result["items"][0]["nested"] == "value"

    def test_attr_count_zero_disables_limit(self) -> None:
        """Kills: max_attr_count > 0 boundary mutation (>= 0 or > 1).

        When max_attr_count is 0, the limit should be disabled (no truncation).
        """
        processor = harden_input(1024, 0, 8)
        event_dict = {"a": 1, "b": 2, "c": 3}
        result = processor(None, "", event_dict)
        assert len(result) == 3

    def test_attr_count_one_keeps_one_key(self) -> None:
        """Kills: max_attr_count boundary — limit=1 keeps exactly 1 key."""
        processor = harden_input(1024, 1, 8)
        event_dict = {"a": 1, "b": 2, "c": 3}
        result = processor(None, "", event_dict)
        assert len(result) == 1

    def test_attr_count_and_condition_both_parts(self) -> None:
        """Kills: `and` -> `or` in max_attr_count > 0 and len(event_dict) > max_attr_count.

        With max_attr_count=5 and only 3 attrs, no truncation should happen.
        The `or` mutant would truncate when max_attr_count > 0 regardless of len.
        """
        processor = harden_input(1024, 5, 8)
        event_dict = {"a": 1, "b": 2, "c": 3}
        result = processor(None, "", event_dict)
        assert len(result) == 3  # not truncated

    def test_attr_count_exact_boundary(self) -> None:
        """Kills: len(event_dict) > max_attr_count -> >= boundary mutation.

        With exactly max_attr_count attrs, no truncation should occur.
        """
        processor = harden_input(1024, 3, 8)
        event_dict = {"a": 1, "b": 2, "c": 3}
        result = processor(None, "", event_dict)
        assert len(result) == 3  # exactly at limit, NOT truncated

    def test_cleaned_values_applied_to_all_keys(self) -> None:
        """Kills: return value of _processor not using _clean_value on values.

        All string values in the returned dict must be cleaned.
        """
        processor = harden_input(1024, 64, 8)
        result = processor(None, "", {"a": "x\x01y", "b": "p\x02q"})
        assert result["a"] == "xy"
        assert result["b"] == "pq"


# ---------------------------------------------------------------------------
# TestSecretDetection
# ---------------------------------------------------------------------------


class TestSecretDetection:
    """Test _detect_secret_in_value from pii.py."""

    def test_detects_aws_access_key(self) -> None:
        assert _detect_secret_in_value("AKIAIOSFODNN7EXAMPLE") is True  # pragma: allowlist secret

    def test_detects_aws_sts_temporary_key(self) -> None:
        assert _detect_secret_in_value("ASIAJEXAMPLEKEYHERE1") is True  # pragma: allowlist secret

    def test_detects_jwt_token(self) -> None:
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"  # pragma: allowlist secret
        assert _detect_secret_in_value(jwt) is True

    def test_detects_github_token_ghp(self) -> None:
        token = "ghp_" + "A" * 36
        assert _detect_secret_in_value(token) is True

    def test_detects_github_token_gho(self) -> None:
        token = "gho_" + "B" * 36
        assert _detect_secret_in_value(token) is True

    def test_detects_github_token_ghs(self) -> None:
        token = "ghs_" + "C" * 36
        assert _detect_secret_in_value(token) is True

    def test_detects_long_hex_string(self) -> None:
        hex_str = "a" * 40
        assert _detect_secret_in_value(hex_str) is True

    def test_detects_long_base64_string(self) -> None:
        b64 = "A" * 40
        assert _detect_secret_in_value(b64) is True

    def test_does_not_flag_short_strings(self) -> None:
        assert _detect_secret_in_value("short") is False
        assert _detect_secret_in_value("abc123") is False

    def test_does_not_flag_normal_trace_id(self) -> None:
        # 32 hex chars — below the 40-char threshold
        trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
        assert _detect_secret_in_value(trace_id) is False

    def test_does_not_flag_normal_english_text(self) -> None:
        assert _detect_secret_in_value("The quick brown fox jumps over the lazy dog") is False
        assert _detect_secret_in_value("This is a normal log message about user activity") is False


# ---------------------------------------------------------------------------
# TestSecretRedaction
# ---------------------------------------------------------------------------


class TestSecretRedaction:
    """Test that sanitize_payload with enabled=True redacts secrets in values."""

    def test_aws_key_value_redacted(self) -> None:
        payload: dict[str, Any] = {"data": "AKIAIOSFODNN7EXAMPLE"}
        result = sanitize_payload(payload, enabled=True)
        assert result["data"] == "***"

    def test_jwt_value_redacted(self) -> None:
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"  # pragma: allowlist secret
        payload: dict[str, Any] = {"auth": jwt}
        result = sanitize_payload(payload, enabled=True)
        assert result["auth"] == "***"

    def test_password_field_name_takes_precedence(self) -> None:
        # Field-name match should redact even without content scan
        payload: dict[str, Any] = {"password": "simple"}
        result = sanitize_payload(payload, enabled=True)
        assert result["password"] == "***"

    def test_nested_secret_values_caught(self) -> None:
        payload: dict[str, Any] = {
            "outer": {
                "credentials": "ghp_" + "X" * 36,
            }
        }
        result = sanitize_payload(payload, enabled=True)
        assert result["outer"]["credentials"] == "***"


# ---------------------------------------------------------------------------
# TestDepthGuard
# ---------------------------------------------------------------------------


class TestDepthGuard:
    """Test depth limit in sanitize_payload."""

    def test_deep_nesting_beyond_max_depth_untouched(self) -> None:
        # Build 10 levels of nesting with a secret at the bottom
        deep: dict[str, Any] = {"token": "ghp_" + "Z" * 36}
        for i in range(9, 0, -1):
            deep = {f"level{i}": deep}
        result = sanitize_payload(deep, enabled=True, max_depth=3)
        # Navigate to the deep token — beyond depth 3, values are untouched
        node: Any = result
        for i in range(1, 10):
            node = node[f"level{i}"]
        assert node["token"] == "ghp_" + "Z" * 36

    def test_apply_rule_depth_32_safety_limit(self) -> None:
        """_apply_rule hard safety limit at depth >= 32 returns node as-is."""
        from undef.telemetry.pii import PIIRule, _apply_rule

        rule = PIIRule(path=("secret",), mode="redact")
        node: dict[str, Any] = {"secret": "hunter2"}
        # At depth >= 32, the rule is not applied
        result = _apply_rule(node, rule, current_path=(), depth=32)
        assert result == {"secret": "hunter2"}  # pragma: allowlist secret

    def test_normal_depth_values_sanitized(self) -> None:
        payload: dict[str, Any] = {
            "level1": {
                "secret": "ghp_" + "Y" * 36,  # pragma: allowlist secret
            }
        }
        result = sanitize_payload(payload, enabled=True, max_depth=8)
        assert result["level1"]["secret"] == "***"


# ---------------------------------------------------------------------------
# TestProtocolResilience
# ---------------------------------------------------------------------------


class TestProtocolResilience:
    """Test propagation guards for oversized headers."""

    @staticmethod
    def _make_scope(
        traceparent: bytes | None = None,
        tracestate: bytes | None = None,
        baggage: bytes | None = None,
    ) -> dict[str, Any]:
        headers: list[tuple[bytes, bytes]] = []
        if traceparent is not None:
            headers.append((b"traceparent", traceparent))
        if tracestate is not None:
            headers.append((b"tracestate", tracestate))
        if baggage is not None:
            headers.append((b"baggage", baggage))
        return {"headers": headers}

    def test_oversized_traceparent_returns_none_trace_id(self) -> None:
        huge = b"x" * 513
        ctx = propagation_mod.extract_w3c_context(self._make_scope(traceparent=huge))
        assert ctx.trace_id is None
        assert ctx.traceparent is None

    def test_normal_traceparent_works(self) -> None:
        tp = b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        ctx = propagation_mod.extract_w3c_context(self._make_scope(traceparent=tp))
        assert ctx.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert ctx.span_id == "00f067aa0ba902b7"

    def test_oversized_tracestate_returns_none(self) -> None:
        tp = b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        big_ts = b"k=" + b"v" * 512
        ctx = propagation_mod.extract_w3c_context(self._make_scope(traceparent=tp, tracestate=big_ts))
        assert ctx.tracestate is None

    def test_tracestate_too_many_pairs_returns_none(self) -> None:
        tp = b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        pairs = ",".join(f"k{i}=v{i}" for i in range(33))
        ctx = propagation_mod.extract_w3c_context(self._make_scope(traceparent=tp, tracestate=pairs.encode()))
        assert ctx.tracestate is None

    def test_normal_tracestate_preserved(self) -> None:
        tp = b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        ctx = propagation_mod.extract_w3c_context(self._make_scope(traceparent=tp, tracestate=b"vendor=value"))
        assert ctx.tracestate == "vendor=value"

    def test_oversized_baggage_returns_none(self) -> None:
        tp = b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        big_baggage = b"k=" + b"v" * 8192
        ctx = propagation_mod.extract_w3c_context(self._make_scope(traceparent=tp, baggage=big_baggage))
        assert ctx.baggage is None

    def test_normal_baggage_preserved(self) -> None:
        tp = b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        ctx = propagation_mod.extract_w3c_context(self._make_scope(traceparent=tp, baggage=b"user=alice"))
        assert ctx.baggage == "user=alice"


# ---------------------------------------------------------------------------
# TestSecurityConfig
# ---------------------------------------------------------------------------


class TestSecurityConfig:
    """Test SecurityConfig from config.py."""

    def test_default_values(self) -> None:
        cfg = SecurityConfig()
        assert cfg.max_attr_value_length == 1024
        assert cfg.max_attr_count == 64
        assert cfg.max_nesting_depth == 8

    def test_env_var_parsing(self) -> None:
        env = {
            "UNDEF_SECURITY_MAX_ATTR_VALUE_LENGTH": "2048",
            "UNDEF_SECURITY_MAX_ATTR_COUNT": "128",
            "UNDEF_SECURITY_MAX_NESTING_DEPTH": "4",
        }
        cfg = TelemetryConfig.from_env(env)
        assert cfg.security.max_attr_value_length == 2048
        assert cfg.security.max_attr_count == 128
        assert cfg.security.max_nesting_depth == 4

    def test_negative_max_attr_value_length_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="max_attr_value_length"):
            SecurityConfig(max_attr_value_length=-1)

    def test_negative_max_attr_count_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="max_attr_count"):
            SecurityConfig(max_attr_count=-1)

    def test_negative_max_nesting_depth_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="max_nesting_depth"):
            SecurityConfig(max_nesting_depth=-1)


# ---------------------------------------------------------------------------
# TestSanitizeSensitiveFieldsProcessor
# ---------------------------------------------------------------------------


class TestSanitizeSensitiveFieldsProcessor:
    """Test the sanitize_sensitive_fields structlog processor."""

    def test_processor_passes_event_dict_through(self) -> None:
        """Verify the processor passes the actual event_dict, not None."""
        processor = sanitize_sensitive_fields(enabled=False)
        event = {"event": "test.ok", "user": "alice"}
        result = processor(None, "", event)
        assert result == {"event": "test.ok", "user": "alice"}

    def test_processor_redacts_when_enabled(self) -> None:
        processor = sanitize_sensitive_fields(enabled=True)
        event: dict[str, Any] = {"event": "test.ok", "password": "secret123"}
        result = processor(None, "", event)
        assert result["password"] == "***"
        assert result["event"] == "test.ok"

    def test_processor_respects_max_depth(self) -> None:
        processor = sanitize_sensitive_fields(enabled=True, max_depth=1)
        event: dict[str, Any] = {"level1": {"password": "deep_secret"}}
        result = processor(None, "", event)
        # At max_depth=1, the nested dict should not be traversed
        assert result["level1"]["password"] == "deep_secret"  # pragma: allowlist secret

    def test_processor_with_max_depth_default_traverses(self) -> None:
        processor = sanitize_sensitive_fields(enabled=True, max_depth=8)
        event: dict[str, Any] = {"level1": {"password": "deep_secret"}}  # pragma: allowlist secret
        result = processor(None, "", event)
        assert result["level1"]["password"] == "***"
