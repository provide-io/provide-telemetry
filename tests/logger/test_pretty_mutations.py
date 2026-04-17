# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests targeting surviving mutation-testing mutants in logger/pretty.py.

These test EXACT hardcoded values for ANSI escape codes and constants,
rather than importing values from the module (which would pass even when
mutmut changes the source).
"""

from __future__ import annotations

from provide.telemetry.logger.pretty import (
    _LEVEL_PAD,
    DIM,
    LEVEL_COLORS,
    NAMED_COLORS,
    RESET,
    PrettyRenderer,
    resolve_color,
)

# ---------------------------------------------------------------------------
# TestLevelColorsExactValues — hardcoded ANSI codes
# ---------------------------------------------------------------------------


class TestLevelColorsExactValues:
    """Verify each LEVEL_COLORS entry matches its exact ANSI escape sequence."""

    def test_critical_is_bold_red(self) -> None:
        assert LEVEL_COLORS["critical"] == "\033[31;1m"

    def test_error_is_red(self) -> None:
        assert LEVEL_COLORS["error"] == "\033[31m"

    def test_warning_is_yellow(self) -> None:
        assert LEVEL_COLORS["warning"] == "\033[33m"

    def test_info_is_green(self) -> None:
        assert LEVEL_COLORS["info"] == "\033[32m"

    def test_debug_is_blue(self) -> None:
        assert LEVEL_COLORS["debug"] == "\033[34m"

    def test_trace_is_cyan(self) -> None:
        assert LEVEL_COLORS["trace"] == "\033[36m"

    def test_critical_differs_from_error(self) -> None:
        """Kills mutant that swaps critical/error values."""
        assert LEVEL_COLORS["critical"] != LEVEL_COLORS["error"]

    def test_all_six_levels_present(self) -> None:
        assert len(LEVEL_COLORS) == 6


# ---------------------------------------------------------------------------
# TestGlobalConstantsExactValues
# ---------------------------------------------------------------------------


class TestGlobalConstantsExactValues:
    def test_reset_is_escape_0m(self) -> None:
        assert RESET == "\033[0m"

    def test_dim_is_escape_2m(self) -> None:
        assert DIM == "\033[2m"

    def test_level_pad_is_9(self) -> None:
        assert _LEVEL_PAD == 9

    def test_level_pad_is_integer(self) -> None:
        assert isinstance(_LEVEL_PAD, int)

    def test_reset_starts_with_escape(self) -> None:
        assert RESET.startswith("\033[")

    def test_dim_starts_with_escape(self) -> None:
        assert DIM.startswith("\033[")

    def test_dim_is_not_reset(self) -> None:
        """Kills mutant that swaps DIM and RESET."""
        assert DIM != RESET

    def test_reset_ends_with_0m(self) -> None:
        assert RESET.endswith("0m")

    def test_dim_ends_with_2m(self) -> None:
        assert DIM.endswith("2m")


# ---------------------------------------------------------------------------
# TestNamedColorsExactValues
# ---------------------------------------------------------------------------


class TestNamedColorsExactValues:
    def test_dim_is_escape_2m(self) -> None:
        assert NAMED_COLORS["dim"] == "\033[2m"

    def test_bold_is_escape_1m(self) -> None:
        assert NAMED_COLORS["bold"] == "\033[1m"

    def test_red_is_escape_31m(self) -> None:
        assert NAMED_COLORS["red"] == "\033[31m"

    def test_green_is_escape_32m(self) -> None:
        assert NAMED_COLORS["green"] == "\033[32m"

    def test_yellow_is_escape_33m(self) -> None:
        assert NAMED_COLORS["yellow"] == "\033[33m"

    def test_blue_is_escape_34m(self) -> None:
        assert NAMED_COLORS["blue"] == "\033[34m"

    def test_cyan_is_escape_36m(self) -> None:
        assert NAMED_COLORS["cyan"] == "\033[36m"

    def test_white_is_escape_37m(self) -> None:
        assert NAMED_COLORS["white"] == "\033[37m"

    def test_none_is_empty_string(self) -> None:
        assert NAMED_COLORS["none"] == ""

    def test_all_nine_entries_present(self) -> None:
        assert len(NAMED_COLORS) == 9

    def test_dim_matches_module_level_dim(self) -> None:
        """Named 'dim' must match the DIM constant."""
        assert NAMED_COLORS["dim"] == DIM

    def test_red_matches_level_colors_error(self) -> None:
        """Named 'red' must match the error level color."""
        assert NAMED_COLORS["red"] == LEVEL_COLORS["error"]


# ---------------------------------------------------------------------------
# TestResolveColorMutations
# ---------------------------------------------------------------------------


class TestResolveColorMutations:
    def test_returns_exact_cyan_escape(self) -> None:
        assert resolve_color("cyan") == "\033[36m"

    def test_returns_exact_red_escape(self) -> None:
        assert resolve_color("red") == "\033[31m"

    def test_returns_exact_bold_escape(self) -> None:
        assert resolve_color("bold") == "\033[1m"

    def test_unknown_returns_empty_not_none(self) -> None:
        result = resolve_color("nonexistent")
        assert result == ""
        assert result is not None


# ---------------------------------------------------------------------------
# TestPrettyRendererOutputExactAnsi
# ---------------------------------------------------------------------------


class TestPrettyRendererOutputExactAnsi:
    """Verify exact ANSI sequences appear in rendered output."""

    def _render(self, event_dict: dict[str, object], **kwargs: object) -> str:
        return PrettyRenderer(colors=True, **kwargs)(None, "info", event_dict)  # type: ignore

    def test_timestamp_wrapped_in_dim_reset(self) -> None:
        ts = "2026-01-01T00:00:00Z"
        output = self._render({"timestamp": ts, "level": "info", "event": "e"})
        assert "\033[2m" + ts + "\033[0m" in output

    def test_info_level_uses_green_escape(self) -> None:
        output = self._render({"level": "info", "event": "e"})
        assert "\033[32m" in output

    def test_error_level_uses_red_escape(self) -> None:
        r = PrettyRenderer(colors=True)
        output = r(None, "info", {"level": "error", "event": "e"})
        assert "\033[31m" in output

    def test_critical_level_uses_bold_red_escape(self) -> None:
        r = PrettyRenderer(colors=True)
        output = r(None, "info", {"level": "critical", "event": "e"})
        assert "\033[31;1m" in output

    def test_warning_level_uses_yellow_escape(self) -> None:
        r = PrettyRenderer(colors=True)
        output = r(None, "info", {"level": "warning", "event": "e"})
        assert "\033[33m" in output

    def test_debug_level_uses_blue_escape(self) -> None:
        r = PrettyRenderer(colors=True)
        output = r(None, "info", {"level": "debug", "event": "e"})
        assert "\033[34m" in output

    def test_trace_level_uses_cyan_escape(self) -> None:
        r = PrettyRenderer(colors=True)
        output = r(None, "info", {"level": "trace", "event": "e"})
        assert "\033[36m" in output

    def test_level_bracket_format_with_color(self) -> None:
        """Kills: bracket string concat mutations."""
        r = PrettyRenderer(colors=True)
        output = r(None, "info", {"level": "info", "event": "e"})
        # Should contain "[" + color + padded_level + RESET + "]"
        assert "[\033[32m" in output
        assert "\033[0m]" in output

    def test_level_bracket_format_without_color(self) -> None:
        """Kills: bracket string concat mutations for no-color path."""
        r = PrettyRenderer(colors=False)
        output = r(None, "info", {"level": "info", "event": "e"})
        # "info" padded to 9 chars
        assert "[info     ]" in output

    def test_level_padding_exact_width(self) -> None:
        """Kills: _LEVEL_PAD mutation (e.g. 9 -> 10)."""
        r = PrettyRenderer(colors=False)
        output = r(None, "info", {"level": "debug", "event": "e"})
        # "debug" is 5 chars, padded to 9 = "debug    "
        assert "[debug    ]" in output

    def test_level_padding_critical(self) -> None:
        """critical = 8 chars, padded to 9 = 'critical '."""
        r = PrettyRenderer(colors=False)
        output = r(None, "info", {"level": "critical", "event": "e"})
        assert "[critical ]" in output

    def test_parts_joined_with_space(self) -> None:
        """Kills: ' '.join -> ''.join mutation."""
        r = PrettyRenderer(colors=False)
        output = r(None, "info", {"timestamp": "TS", "level": "info", "event": "msg"})
        # Parts should be space-separated: "TS [info     ] msg"
        assert "TS " in output
        assert "] msg" in output

    def test_key_equals_value_format(self) -> None:
        """Kills: '=' separator mutation."""
        r = PrettyRenderer(colors=False)
        output = r(None, "info", {"level": "info", "event": "e", "k": "v"})
        assert "k='v'" in output

    def test_key_color_wraps_key_with_reset(self) -> None:
        """Verify key color + RESET sequence."""
        cyan = "\033[36m"
        r = PrettyRenderer(colors=True, key_color=cyan)
        output = r(None, "info", {"level": "info", "event": "e", "mykey": "val"})
        assert cyan + "mykey" + "\033[0m" in output

    def test_value_color_wraps_value_with_reset(self) -> None:
        """Verify value color + RESET sequence."""
        blue = "\033[34m"
        r = PrettyRenderer(colors=True, value_color=blue)
        output = r(None, "info", {"level": "info", "event": "e", "k": "v"})
        assert blue + "'v'" + "\033[0m" in output
