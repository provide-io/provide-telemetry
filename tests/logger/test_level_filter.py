# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for _parse_module_levels() and _LevelFilter / make_level_filter()."""

from __future__ import annotations

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
