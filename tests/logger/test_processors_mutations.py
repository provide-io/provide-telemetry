# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests targeting surviving mutation-testing mutants in logger/processors.py."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest
import structlog

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger.processors import (
    _compute_error_fingerprint,
    add_error_fingerprint,
    add_standard_fields,
    apply_sampling,
    enforce_event_schema,
    harden_input,
    merge_runtime_context,
    sanitize_sensitive_fields,
)


@pytest.fixture(autouse=True)
def _reset_runtime() -> None:
    """Reset active runtime config so processor tests use factory-captured values."""
    from provide.telemetry import runtime as runtime_mod

    runtime_mod.reset_runtime_for_tests()


# ── merge_runtime_context: trace_id / span_id key names ─────────────


class TestMergeRuntimeContextKeys:
    def test_trace_id_key_is_exact(self) -> None:
        """Kills: 'trace_id' → 'XXtrace_idXX' in both .get() and assignment."""
        with (
            patch("undef.telemetry.logger.processors.get_trace_id", return_value="abc123"),
            patch("undef.telemetry.logger.processors.get_span_id", return_value=None),
            patch("undef.telemetry.logger.processors.get_context", return_value={}),
        ):
            result = merge_runtime_context(None, "", {"event": "x"})
        assert "trace_id" in result
        assert result["trace_id"] == "abc123"
        assert "span_id" not in result

    def test_span_id_key_is_exact(self) -> None:
        """Kills: 'span_id' → 'XXspan_idXX' in both .get() and assignment."""
        with (
            patch("undef.telemetry.logger.processors.get_trace_id", return_value=None),
            patch("undef.telemetry.logger.processors.get_span_id", return_value="def456"),
            patch("undef.telemetry.logger.processors.get_context", return_value={}),
        ):
            result = merge_runtime_context(None, "", {"event": "x"})
        assert "span_id" in result
        assert result["span_id"] == "def456"
        assert "trace_id" not in result

    def test_both_trace_and_span_set(self) -> None:
        """Both keys present when both values are non-None."""
        with (
            patch("undef.telemetry.logger.processors.get_trace_id", return_value="t1"),
            patch("undef.telemetry.logger.processors.get_span_id", return_value="s1"),
            patch("undef.telemetry.logger.processors.get_context", return_value={}),
        ):
            result = merge_runtime_context(None, "", {"event": "x"})
        assert result["trace_id"] == "t1"
        assert result["span_id"] == "s1"

    def test_neither_trace_nor_span_set(self) -> None:
        """Neither key present when both values are None."""
        with (
            patch("undef.telemetry.logger.processors.get_trace_id", return_value=None),
            patch("undef.telemetry.logger.processors.get_span_id", return_value=None),
            patch("undef.telemetry.logger.processors.get_context", return_value={}),
        ):
            result = merge_runtime_context(None, "", {"event": "x"})
        assert "trace_id" not in result
        assert "span_id" not in result


# ── add_standard_fields: error taxonomy key checks ───────────────────


class TestAddStandardFieldsErrorTaxonomy:
    def test_adds_error_taxonomy_when_exc_name_present(self) -> None:
        """Kills: 'exc_name' → 'XXexc_nameXX' in the `in` check."""
        config = TelemetryConfig.from_env({})
        processor = add_standard_fields(config)
        event_dict: dict[str, object] = {
            "event": "app.error.occurred",
            "exc_name": "ValueError",
        }
        result = processor(None, "", event_dict)
        assert "error_type" in result
        assert result["error_name"] == "ValueError"

    def test_skips_taxonomy_when_error_type_already_present(self) -> None:
        """Kills: 'error_type' → 'XXerror_typeXX' in the `not in` check."""
        config = TelemetryConfig.from_env({})
        processor = add_standard_fields(config)
        event_dict: dict[str, object] = {
            "event": "app.error.occurred",
            "exc_name": "ValueError",
            "error_type": "custom",
        }
        result = processor(None, "", event_dict)
        assert result["error_type"] == "custom"
        # Should NOT have overwritten with classify_error output
        assert result.get("error_code") is None

    def test_skips_taxonomy_when_no_exc_name(self) -> None:
        """Kills: 'exc_name' → 'XXexc_nameXX' in the `in` check."""
        config = TelemetryConfig.from_env({})
        processor = add_standard_fields(config)
        event_dict: dict[str, object] = {"event": "app.request.ok"}
        result = processor(None, "", event_dict)
        assert "error_type" not in result

    def test_passes_status_code_to_classify_error(self) -> None:
        """Kills: 'status_code' key string and int isinstance check."""
        config = TelemetryConfig.from_env({})
        processor = add_standard_fields(config)
        event_dict: dict[str, object] = {
            "event": "app.error.occurred",
            "exc_name": "RuntimeError",
            "status_code": 503,
        }
        result = processor(None, "", event_dict)
        assert result["error_type"] == "server"
        assert result["error_code"] == "503"

    def test_non_int_status_code_treated_as_none(self) -> None:
        """Kills: isinstance(status_code, int) boundary."""
        config = TelemetryConfig.from_env({})
        processor = add_standard_fields(config)
        event_dict: dict[str, object] = {
            "event": "app.error.occurred",
            "exc_name": "RuntimeError",
            "status_code": "not-a-number",
        }
        result = processor(None, "", event_dict)
        # Non-int status_code → passed as None → classify_error returns 'internal'
        assert result["error_type"] == "internal"
        assert result["error_code"] == "0"

    def test_exc_name_value_passed_to_classify_error(self) -> None:
        """Kills: str(event_dict['exc_name']) → str(event_dict['XXexc_nameXX'])."""
        config = TelemetryConfig.from_env({})
        processor = add_standard_fields(config)
        event_dict: dict[str, object] = {
            "event": "app.error.occurred",
            "exc_name": "KeyError",
        }
        with patch(
            "undef.telemetry.slo.classify_error",
            wraps=lambda exc, _sc=None: {"error_type": "internal", "error_code": "0", "error_name": exc},
        ) as mock_classify:
            result = processor(None, "", event_dict)
        mock_classify.assert_called_once_with("KeyError", None)
        assert result["error_name"] == "KeyError"

    def test_taxonomy_skipped_when_include_error_taxonomy_false(self) -> None:
        """Taxonomy should not be added when slo.include_error_taxonomy is False."""
        config = TelemetryConfig.from_env({"PROVIDE_SLO_INCLUDE_ERROR_TAXONOMY": "false"})
        processor = add_standard_fields(config)
        event_dict: dict[str, object] = {
            "event": "app.error.occurred",
            "exc_name": "ValueError",
        }
        result = processor(None, "", event_dict)
        assert "error_type" not in result


# ── apply_sampling: signal, key names, dropped event ─────────────────


class TestApplySamplingMutants:
    def test_signal_is_logs(self) -> None:
        """Kills: 'logs' → 'XXlogsXX' in should_sample call."""
        with patch(
            "provide.telemetry.sampling.should_sample",
            return_value=True,
        ) as mock_sample:
            apply_sampling(None, "", {"event": "app.test.ok"})
        mock_sample.assert_called_once_with("logs", "app.test.ok")

    def test_event_key_read_correctly(self) -> None:
        """Kills: 'event' key → 'XXeventXX'."""
        with patch(
            "provide.telemetry.sampling.should_sample",
            return_value=True,
        ) as mock_sample:
            apply_sampling(None, "", {"event": "my.specific.event"})
        mock_sample.assert_called_once_with("logs", "my.specific.event")

    def test_dropped_event_raises_drop_event(self) -> None:
        """When sampling rejects, DropEvent is raised to suppress the log."""
        with (
            patch(
                "provide.telemetry.sampling.should_sample",
                return_value=False,
            ),
            pytest.raises(structlog.DropEvent),
        ):
            apply_sampling(None, "", {"event": "app.test.ok"})

    def test_sampled_event_passes_through(self) -> None:
        """When sampled, original event_dict is returned unchanged."""
        original: dict[str, object] = {"event": "app.test.ok", "extra": "data"}
        with patch(
            "provide.telemetry.sampling.should_sample",
            return_value=True,
        ):
            result = apply_sampling(None, "", original)
        assert result is original


# ── enforce_event_schema: strict_event_name=True when strict_schema ──


class TestEnforceEventSchemaMutants:
    def test_strict_schema_forces_strict_event_name_true(self) -> None:
        """Kills: strict_event_name=True → strict_event_name=False."""
        config = TelemetryConfig.from_env({"PROVIDE_TELEMETRY_STRICT_SCHEMA": "true"})
        processor = enforce_event_schema(config)
        # A non-dotted name should fail when strict_event_name is True
        with patch(
            "provide.telemetry.logger.processors.validate_event_name",
        ) as mock_validate:
            processor(None, "", {"event": "app.test.ok"})
        mock_validate.assert_called_once_with("app.test.ok", strict_event_name=True)

    def test_non_strict_schema_uses_config_value(self) -> None:
        """When strict_schema=False, strict_event_name comes from event_schema config."""
        config = TelemetryConfig.from_env(
            {
                "PROVIDE_TELEMETRY_STRICT_SCHEMA": "false",
                "PROVIDE_TELEMETRY_STRICT_EVENT_NAME": "false",
            }
        )
        processor = enforce_event_schema(config)
        with patch(
            "provide.telemetry.logger.processors.validate_event_name",
        ) as mock_validate:
            processor(None, "", {"event": "anything"})
        mock_validate.assert_called_once_with("anything", strict_event_name=False)

    def test_required_keys_passed_when_strict(self) -> None:
        """Kills: required_keys mutations."""
        config = TelemetryConfig.from_env(
            {
                "PROVIDE_TELEMETRY_STRICT_SCHEMA": "true",
                "PROVIDE_TELEMETRY_REQUIRED_KEYS": "service,env",
            }
        )
        processor = enforce_event_schema(config)
        with (
            patch(
                "provide.telemetry.logger.processors.validate_event_name",
            ),
            patch(
                "provide.telemetry.logger.processors.validate_required_keys",
            ) as mock_req,
        ):
            event_dict: dict[str, object] = {"event": "app.test.ok", "service": "s", "env": "e"}
            processor(None, "", event_dict)
        mock_req.assert_called_once()
        actual_keys = mock_req.call_args[0][1]
        assert "service" in actual_keys
        assert "env" in actual_keys

    def test_required_keys_respected_when_not_strict(self) -> None:
        """When strict_schema=False, required_keys from config are still enforced."""
        config = TelemetryConfig.from_env(
            {
                "PROVIDE_TELEMETRY_STRICT_SCHEMA": "false",
                "PROVIDE_TELEMETRY_REQUIRED_KEYS": "service,env",
            }
        )
        processor = enforce_event_schema(config)
        with (
            patch(
                "provide.telemetry.logger.processors.validate_event_name",
            ),
            patch(
                "provide.telemetry.logger.processors.validate_required_keys",
            ) as mock_req,
        ):
            processor(None, "", {"event": "app.test.ok"})
        actual_keys = mock_req.call_args[0][1]
        assert "service" in actual_keys
        assert "env" in actual_keys


# ── add_error_fingerprint: tuple shape and type guards ────────────────


class TestAddErrorFingerprintGuards:
    def test_two_tuple_exc_info_does_not_produce_fingerprint(self) -> None:
        """Kills: len(exc_info) == 3 → == 2 or != 3."""
        # A 2-tuple is not a valid exc_info — should not trigger fingerprinting
        event: dict[str, object] = {"event": "error", "exc_info": (ValueError, ValueError("x"))}
        result = add_error_fingerprint(None, "", event)
        assert "error_fingerprint" not in result

    def test_four_tuple_exc_info_does_not_produce_fingerprint(self) -> None:
        """Kills: len(exc_info) == 3 → >= 3 (four-element tuple satisfies >= but not ==)."""
        event: dict[str, object] = {
            "event": "error",
            "exc_info": (ValueError, ValueError("x"), None, "extra"),
        }
        result = add_error_fingerprint(None, "", event)
        assert "error_fingerprint" not in result

    def test_three_tuple_with_none_exception_does_not_produce_fingerprint(self) -> None:
        """Kills: exc_info[1] is not None → is None."""
        event: dict[str, object] = {"event": "error", "exc_info": (type(None), None, None)}
        result = add_error_fingerprint(None, "", event)
        assert "error_fingerprint" not in result

    def test_base_exception_not_subclass_of_exception_is_handled(self) -> None:
        """Kills: isinstance(exc_info, BaseException) → isinstance(exc_info, Exception)."""
        # KeyboardInterrupt is a BaseException but not an Exception
        # Raise it so __traceback__ is populated, making the exact-value check meaningful
        exc: BaseException | None = None
        try:
            raise KeyboardInterrupt("interrupted")
        except KeyboardInterrupt as e:
            exc = e
            event: dict[str, object] = {"event": "error", "exc_info": exc}
            result = add_error_fingerprint(None, "", event)
        assert "error_fingerprint" in result
        assert result["error_fingerprint"] == _compute_error_fingerprint("KeyboardInterrupt", exc.__traceback__)

    def test_three_tuple_with_valid_exception_does_produce_fingerprint(self) -> None:
        """Verifies the len==3 and is-not-None fast path."""
        try:
            raise RuntimeError("test")
        except RuntimeError:
            exc_info = sys.exc_info()
        event: dict[str, object] = {"event": "error", "exc_info": exc_info}
        result = add_error_fingerprint(None, "", event)
        assert "error_fingerprint" in result

    def test_3tuple_with_none_traceback_still_produces_fingerprint(self) -> None:
        """Kills: exc_info[1] is not None → exc_info[2] is not None (mutmut_12)."""
        exc = ValueError("no traceback")
        event: dict[str, object] = {
            "event": "error",
            "exc_info": (ValueError, exc, None),  # exc[1] non-None, exc[2] = None
        }
        result = add_error_fingerprint(None, "", event)
        assert "error_fingerprint" in result

    def test_3tuple_fingerprint_type_name_from_exception_not_none(self) -> None:
        """Kills: type(exc_info[1]).__name__ → type(None).__name__ (mutmut_15, mutmut_16)."""
        exc = ValueError("test")
        event: dict[str, object] = {
            "event": "error",
            "exc_info": (ValueError, exc, None),  # exc[1]=ValueError, exc[2]=None
        }
        result = add_error_fingerprint(None, "", event)
        expected = _compute_error_fingerprint("ValueError", None)
        not_expected = _compute_error_fingerprint("NoneType", None)
        assert result["error_fingerprint"] == expected
        assert result["error_fingerprint"] != not_expected

    def test_3tuple_fingerprint_uses_actual_traceback_not_none(self) -> None:
        """Kills: _compute_error_fingerprint(name, exc_info[2]) → (..., None) (mutmut_21)."""
        try:
            raise RuntimeError("test")
        except RuntimeError:
            exc_info = sys.exc_info()
        assert exc_info[2] is not None, "test requires a real traceback"
        event: dict[str, object] = {"event": "error", "exc_info": exc_info}
        result = add_error_fingerprint(None, "", event)
        no_tb_hash = _compute_error_fingerprint("RuntimeError", None)
        with_tb_hash = _compute_error_fingerprint("RuntimeError", exc_info[2])
        assert result["error_fingerprint"] == with_tb_hash
        assert result["error_fingerprint"] != no_tb_hash

    def test_exc_name_fallback_uses_exact_name_not_none_string(self) -> None:
        """Kills: str(exc_name) → str(None) in exc_name fallback path (mutmut_47)."""
        event: dict[str, object] = {"event": "error", "exc_name": "TimeoutError"}
        result = add_error_fingerprint(None, "", event)
        expected = _compute_error_fingerprint("TimeoutError", None)
        unexpected = _compute_error_fingerprint("None", None)
        assert result["error_fingerprint"] == expected
        assert result["error_fingerprint"] != unexpected


# ── harden_input: exact boundary values ──────────────────────────────


class TestHardenInputBoundaries:
    def test_string_at_exact_max_length_not_truncated(self) -> None:
        """Kills: len(cleaned) > max_value_length → >=."""
        proc = harden_input(max_value_length=5, max_attr_count=0, max_depth=5)
        result = proc(None, "", {"event": "x", "key": "hello"})  # exactly 5 chars
        assert result["key"] == "hello"  # not truncated

    def test_string_one_over_max_length_truncated(self) -> None:
        """Companion to above — confirms truncation does fire at len+1."""
        proc = harden_input(max_value_length=5, max_attr_count=0, max_depth=5)
        result = proc(None, "", {"event": "x", "key": "hello!"})  # 6 chars
        assert result["key"] == "hello"

    def test_max_attr_count_zero_keeps_all_attributes(self) -> None:
        """Kills: max_attr_count > 0 → >= 0 (would truncate even with count=0)."""
        proc = harden_input(max_value_length=100, max_attr_count=0, max_depth=5)
        event: dict[str, object] = {"event": "x", "a": 1, "b": 2, "c": 3}
        result = proc(None, "", event)
        assert len(result) == 4  # all keys preserved

    def test_attrs_at_exact_max_count_not_dropped(self) -> None:
        """Kills: len(event_dict) > max_attr_count → >=."""
        proc = harden_input(max_value_length=100, max_attr_count=3, max_depth=5)
        event: dict[str, object] = {"event": "x", "a": 1, "b": 2}  # exactly 3 keys
        result = proc(None, "", event)
        assert len(result) == 3  # not truncated

    def test_attrs_one_over_max_count_truncated(self) -> None:
        """Companion — confirms attr dropping fires at count+1."""
        proc = harden_input(max_value_length=100, max_attr_count=3, max_depth=5)
        event: dict[str, object] = {"event": "x", "a": 1, "b": 2, "c": 3}  # 4 keys
        result = proc(None, "", event)
        assert len(result) == 3

    def test_depth_zero_does_not_recurse_into_nested_dict(self) -> None:
        """Kills: depth < max_depth → depth <= max_depth.

        At max_depth=0: depth=0 < 0 is False → dict not recursed, control chars survive.
        At max_depth=0 with mutation <=: depth=0 <= 0 is True → dict IS recursed.
        """
        proc = harden_input(max_value_length=100, max_attr_count=0, max_depth=0)
        event: dict[str, object] = {"event": "x", "nested": {"inner": "\x01dirty"}}
        result = proc(None, "", event)
        # Nested dict should be returned as-is (no recursion at depth=0 with max_depth=0)
        assert result["nested"] == {"inner": "\x01dirty"}

    def test_depth_one_recurses_one_level(self) -> None:
        """Companion — with max_depth=1, depth=0 < 1 is True → recurse and clean."""
        proc = harden_input(max_value_length=100, max_attr_count=0, max_depth=1)
        result = proc(None, "", {"event": "x", "nested": {"inner": "\x01dirty"}})
        assert result["nested"] == {"inner": "dirty"}

    def test_dict_recursion_increments_depth_by_one_not_two(self) -> None:
        """Kills: depth + 1 → depth + 2 for dict recursion (mutmut_15)."""
        proc = harden_input(max_value_length=100, max_attr_count=0, max_depth=2)
        event: dict[str, object] = {
            "event": "x",
            "outer": {"middle": {"inner": "\x01dirty"}},
        }
        result = proc(None, "", event)
        assert result["outer"]["middle"]["inner"] == "dirty"

    def test_list_recursion_increments_depth_by_one_kills_minus_one_and_plus_two(self) -> None:
        """Kills: depth + 1 → depth - 1 (mutmut_22) and depth + 2 (mutmut_23) for lists."""
        proc = harden_input(max_value_length=100, max_attr_count=0, max_depth=2)
        event: dict[str, object] = {"event": "x", "items": [["\x01dirty"]]}
        result = proc(None, "", event)
        assert result["items"] == [["dirty"]]


# ── sanitize_sensitive_fields: max_depth default ─────────────────────


class TestSanitizeSensitiveFieldsDefault:
    def test_default_max_depth_is_8(self) -> None:
        """Kills: max_depth=8 → max_depth=7 or other value."""
        with patch("provide.telemetry.pii.sanitize_payload") as mock:
            mock.return_value = {}
            processor = sanitize_sensitive_fields(enabled=True)
            processor(None, "", {"event": "x"})
        mock.assert_called_once_with({"event": "x"}, True, max_depth=8)

    def test_custom_max_depth_forwarded(self) -> None:
        """Verifies max_depth param is passed through."""
        with patch("provide.telemetry.pii.sanitize_payload") as mock:
            mock.return_value = {}
            processor = sanitize_sensitive_fields(enabled=True, max_depth=3)
            processor(None, "", {"event": "x"})
        mock.assert_called_once_with({"event": "x"}, True, max_depth=3)
