# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for _parse_module_levels() and _LevelFilter / make_level_filter()."""

from __future__ import annotations

import logging
from typing import Any

import pytest
import structlog

from provide.telemetry.config import _parse_module_levels
from provide.telemetry.exceptions import ConfigurationError
from provide.telemetry.logger.processors import _LevelFilter, make_level_filter

# ── _parse_module_levels ─────────────────────────────────────────────────────


class TestParseModuleLevels:
    def test_empty_string_returns_empty_dict(self) -> None:
        assert _parse_module_levels("") == {}

    def test_whitespace_only_returns_empty_dict(self) -> None:
        assert _parse_module_levels("   ") == {}

    def test_single_pair(self) -> None:
        assert _parse_module_levels("asyncio=WARNING") == {"asyncio": "WARNING"}

    def test_multiple_pairs(self) -> None:
        result = _parse_module_levels("asyncio=WARNING,undef.server=DEBUG")
        assert result == {"asyncio": "WARNING", "undef.server": "DEBUG"}

    def test_pair_missing_equals_is_skipped(self) -> None:
        assert _parse_module_levels("asyncioWARNING") == {}

    def test_pair_with_empty_module_name_is_skipped(self) -> None:
        assert _parse_module_levels("=DEBUG") == {}

    def test_level_is_normalized_to_uppercase(self) -> None:
        result = _parse_module_levels("asyncio=warning")
        assert result == {"asyncio": "WARNING"}

    def test_whitespace_around_pairs_is_stripped(self) -> None:
        result = _parse_module_levels("  asyncio = WARNING  ,  undef = DEBUG  ")
        assert result == {"asyncio": "WARNING", "undef": "DEBUG"}

    def test_mixed_valid_and_invalid_pairs(self) -> None:
        result = _parse_module_levels("asyncio=WARNING,bad_pair,undef=DEBUG")
        assert result == {"asyncio": "WARNING", "undef": "DEBUG"}

    def test_extra_equals_in_value_raises_config_error_not_value_error(self) -> None:
        """Kills: split('=', 1) maxsplit removal AND rsplit mutation.

        Input 'module=name=DEBUG' (last segment is a valid level name):
        - Correct split('=', 1): ('module', 'name=DEBUG') → _normalize_level('name=DEBUG') → ConfigurationError.
        - rsplit('=', 1) mutant: ('module=name', 'DEBUG') → no error, returns {'module=name': 'DEBUG'}.
        - split('=') mutant (no maxsplit): ['module', 'name', 'DEBUG'] → ValueError (too many to unpack).
        Only the correct code raises ConfigurationError.
        """
        with pytest.raises(ConfigurationError):
            _parse_module_levels("module=name=DEBUG")

    def test_module_is_key_not_value(self) -> None:
        """Kills: module/level_str unpacking swap — module must be the key, level the value."""
        result = _parse_module_levels("asyncio=DEBUG")
        assert "asyncio" in result
        assert result["asyncio"] == "DEBUG"
        assert "DEBUG" not in result


# ── _LevelFilter / make_level_filter ─────────────────────────────────────────


class TestLevelFilter:
    def test_make_level_filter_returns_level_filter_instance(self) -> None:
        flt = make_level_filter("INFO", {})
        assert callable(flt)

    def test_event_at_threshold_passes_through(self) -> None:
        flt = make_level_filter("INFO", {})
        event: dict[str, Any] = {"event": "hello", "level": "info"}
        assert flt(None, "info", event) is event

    def test_event_above_threshold_passes_through(self) -> None:
        flt = make_level_filter("INFO", {})
        event: dict[str, Any] = {"event": "oh no", "level": "error"}
        assert flt(None, "error", event) is event

    def test_event_below_threshold_raises_drop_event(self) -> None:
        flt = make_level_filter("WARNING", {})
        with pytest.raises(structlog.DropEvent):
            flt(None, "debug", {"event": "noisy", "level": "debug"})

    def test_module_override_raises_drop_for_suppressed_module(self) -> None:
        flt = make_level_filter("DEBUG", {"asyncio": "WARNING"})
        with pytest.raises(structlog.DropEvent):
            flt(None, "debug", {"event": "tick", "level": "debug", "logger_name": "asyncio"})

    def test_module_override_passes_for_allowed_level(self) -> None:
        flt = make_level_filter("DEBUG", {"asyncio": "WARNING"})
        event: dict[str, Any] = {"event": "warn", "level": "warning", "logger_name": "asyncio"}
        assert flt(None, "warning", event) is event

    def test_longest_prefix_wins(self) -> None:
        flt = make_level_filter("DEBUG", {"undef": "WARNING", "undef.server": "DEBUG"})
        # "undef.server.api" matches "undef.server" (longer prefix) — DEBUG allowed
        event: dict[str, Any] = {"event": "x", "level": "debug", "logger_name": "undef.server.api"}
        assert flt(None, "debug", event) is event

    def test_no_matching_prefix_uses_default(self) -> None:
        flt = make_level_filter("WARNING", {"asyncio": "DEBUG"})
        with pytest.raises(structlog.DropEvent):
            flt(None, "debug", {"event": "x", "level": "debug", "logger_name": "someother"})

    def test_logger_key_used_when_logger_name_absent(self) -> None:
        flt = make_level_filter("DEBUG", {"asyncio": "WARNING"})
        with pytest.raises(structlog.DropEvent):
            flt(None, "debug", {"event": "x", "level": "debug", "logger": "asyncio"})

    def test_method_name_used_as_level_fallback(self) -> None:
        flt = make_level_filter("WARNING", {})
        with pytest.raises(structlog.DropEvent):
            # No "level" key in event_dict — falls back to method_name "debug"
            flt(None, "debug", {"event": "x"})


# ── _LevelFilter internal state ───────────────────────────────────────────────


class TestLevelFilterInternals:
    """Inspect _LevelFilter slot attributes to kill specific mutants."""

    def test_default_numeric_is_debug_for_debug_level(self) -> None:
        """Kills: fallback INFO mutation — 'DEBUG' must map to logging.DEBUG."""
        flt = _LevelFilter("DEBUG", {})
        assert flt._default_numeric == logging.DEBUG

    def test_default_numeric_falls_back_to_info_for_unknown_level(self) -> None:
        """Kills: fallback constant mutation — unknown level falls back to logging.INFO."""
        flt = _LevelFilter("NOTAREAL", {})
        assert flt._default_numeric == logging.INFO

    def test_module_numerics_stores_integer_level(self) -> None:
        """Kills: .lower() removal in module_numerics dict — 'WARNING' must resolve to logging.WARNING."""
        flt = _LevelFilter("INFO", {"asyncio": "WARNING"})
        assert flt._module_numerics["asyncio"] == logging.WARNING

    def test_sorted_prefixes_are_longest_first(self) -> None:
        """Kills: key=len removal and reverse=True removal — longer prefixes must come first.

        'ba' is added so alpha-reversed order ('ba','abc','ab','a') differs from
        length-first order ('abc','ab'/'ba','a'), distinguishing key=len from key=None.
        """
        flt = _LevelFilter("INFO", {"a": "INFO", "abc": "INFO", "ab": "INFO", "ba": "INFO"})
        assert flt._sorted_prefixes[0] == "abc"
        assert flt._sorted_prefixes[-1] == "a"

    def test_module_numerics_fallback_for_unknown_level(self) -> None:
        """Kills: module_numerics fallback None/removed — unknown level must yield logging.INFO."""
        flt = _LevelFilter("INFO", {"mod": "UNKNOWNLEVEL"})
        assert flt._module_numerics["mod"] == logging.INFO

    def test_uppercase_level_in_event_dict_is_handled(self) -> None:
        """Kills: .lower() removal on event_dict level — uppercase 'WARNING' must pass threshold."""
        flt = make_level_filter("INFO", {})
        event: dict[str, Any] = {"event": "x", "level": "WARNING"}
        assert flt(None, "warning", event) is event

    def test_break_stops_at_first_matching_prefix(self) -> None:
        """Kills: break removal — must use the longest-prefix match only.

        'undef.server' (longer) maps to ERROR; 'undef' (shorter) maps to DEBUG.
        'undef.server.api' must match 'undef.server' first → ERROR threshold → debug dropped.
        Without break the loop would continue to 'undef' → DEBUG → debug passes.
        """
        flt = make_level_filter("INFO", {"undef": "DEBUG", "undef.server": "ERROR"})
        with pytest.raises(structlog.DropEvent):
            flt(None, "debug", {"event": "x", "level": "debug", "logger_name": "undef.server.api"})

    def test_no_logger_name_or_logger_key_uses_default_threshold(self) -> None:
        """Kills: logger_name/logger fallback — absent keys mean default threshold applies."""
        flt = make_level_filter("WARNING", {"asyncio": "DEBUG"})
        with pytest.raises(structlog.DropEvent):
            # No logger_name or logger key → empty string → no prefix match → WARNING threshold
            flt(None, "debug", {"event": "x", "level": "debug"})

    def test_empty_string_fallback_not_xxxx_for_missing_logger_keys(self) -> None:
        """Kills: empty-string fallback mutation ('XXXX') for missing logger_name/logger.

        Module 'XXXX' has a higher threshold than default.
        With correct fallback '': no prefix match → default INFO threshold → info event passes.
        With mutant fallback 'XXXX': matches 'XXXX' prefix → WARNING threshold → info dropped.
        """
        flt = make_level_filter("INFO", {"XXXX": "WARNING"})
        event: dict[str, Any] = {"event": "x", "level": "info"}
        assert flt(None, "info", event) is event

    def test_unknown_method_name_uses_info_level_fallback(self) -> None:
        """Kills: event_level fallback None/removed.

        An unknown method_name like 'verbose' is not in _FAST_LEVEL_LOOKUP.
        Correct: fallback INFO(20) >= DEBUG(10) threshold → event passes.
        With None fallback: None < 10 raises TypeError → test fails → kills mutant.
        """
        flt = make_level_filter("DEBUG", {})
        event: dict[str, Any] = {"event": "x"}  # no 'level' key → method_name used
        assert flt(None, "verbose", event) is event

    def test_level_key_takes_precedence_over_method_name(self) -> None:
        """Kills: 'level' key mutations (None key, XXlevelXX, LEVEL).

        When 'level' key is present, it overrides method_name for event_level lookup.
        method_name='debug' would give DEBUG(10) < INFO(20) → drop.
        But 'level': 'warning' gives WARNING(30) >= INFO(20) → passes.
        Mutants that ignore the 'level' key would use method_name → drop → test fails.
        """
        flt = make_level_filter("INFO", {})
        event: dict[str, Any] = {"event": "x", "level": "warning"}
        assert flt(None, "debug", event) is event
