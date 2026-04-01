# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import io
import sys
from typing import Any

import pytest
import structlog

from provide.telemetry.logger.core import _reset_logging_for_tests, configure_logging
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
# Helpers
# ---------------------------------------------------------------------------


def _make(event_dict: dict[str, Any], colors: bool = True, **kwargs: Any) -> str:
    return PrettyRenderer(colors=colors, **kwargs)(None, "info", event_dict)


def _base(level: str = "info", event: str = "test.event") -> dict[str, Any]:
    return {"timestamp": "2026-03-14T12:00:00Z", "level": level, "event": event}


# ---------------------------------------------------------------------------
# TestPrettyRendererColors
# ---------------------------------------------------------------------------


class TestPrettyRendererColors:
    def test_info_color_applied(self) -> None:
        output = _make(_base("info"))
        assert LEVEL_COLORS["info"] in output

    def test_error_color_applied(self) -> None:
        output = _make(_base("error"))
        assert LEVEL_COLORS["error"] in output

    def test_warning_color_applied(self) -> None:
        output = _make(_base("warning"))
        assert LEVEL_COLORS["warning"] in output

    def test_debug_color_applied(self) -> None:
        output = _make(_base("debug"))
        assert LEVEL_COLORS["debug"] in output

    def test_trace_color_applied(self) -> None:
        output = _make(_base("trace"))
        assert LEVEL_COLORS["trace"] in output

    def test_critical_color_applied(self) -> None:
        output = _make(_base("critical"))
        assert LEVEL_COLORS["critical"] in output

    def test_level_padded_to_9_chars(self) -> None:
        # Find the bracketed level substring — must be exactly "[" + 9 chars + "]" = 11
        # When colors are off the structure is literal: [info     ]
        output = _make(_base("info"), colors=False)
        # extract between first "[" and first "]"
        start = output.index("[")
        end = output.index("]", start)
        bracketed_content = output[start + 1 : end]
        assert len(bracketed_content) == _LEVEL_PAD
        assert len("[" + bracketed_content + "]") == _LEVEL_PAD + 2

    def test_timestamp_dimmed(self) -> None:
        ts = "2026-03-14T12:00:00Z"
        output = _make({"timestamp": ts, "level": "info", "event": "e"})
        assert DIM + ts + RESET in output

    def test_no_ansi_when_colors_false(self) -> None:
        output = _make(_base("info"), colors=False)
        assert "\033" not in output

    def test_unknown_level_no_color(self) -> None:
        output = _make({"timestamp": "ts", "level": "custom", "event": "e"})
        # No color prefix for unknown level — level still appears
        assert "custom" in output
        # The color for unknown level is "" so no color escape before it inside brackets
        # Find the bracketed section and confirm no ESC code directly after "["
        bracket_start = output.index("[")
        char_after_bracket = output[bracket_start + 1]
        assert char_after_bracket != "\033"


# ---------------------------------------------------------------------------
# TestPrettyRendererFormat
# ---------------------------------------------------------------------------


class TestPrettyRendererFormat:
    def test_extra_keys_as_key_value(self) -> None:
        d = _base()
        d["foo"] = "bar"
        output = _make(d)
        assert "foo='bar'" in output

    def test_extra_keys_sorted(self) -> None:
        d = _base()
        d["zebra"] = 1
        d["apple"] = 2
        output = _make(d, colors=False)
        apple_pos = output.index("apple=")
        zebra_pos = output.index("zebra=")
        assert apple_pos < zebra_pos

    def test_no_extra_keys_no_trailing(self) -> None:
        output = _make(_base(), colors=False)
        assert not output.endswith(" ")

    def test_missing_timestamp_no_dim(self) -> None:
        output = _make({"level": "info", "event": "e"})
        assert DIM not in output

    def test_event_is_in_output(self) -> None:
        output = _make({"level": "info", "event": "auth.login.complete"})
        assert "auth.login.complete" in output

    def test_reset_present_with_colors(self) -> None:
        output = _make(_base())
        assert RESET in output


# ---------------------------------------------------------------------------
# TestPrettyRendererIntegration
# ---------------------------------------------------------------------------


class TestPrettyRendererIntegration:
    def test_configure_logging_pretty_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        structlog.reset_defaults()
        _reset_logging_for_tests()

        class _FakeTTY(io.StringIO):
            def isatty(self) -> bool:
                return True

        fake_stderr = _FakeTTY()
        monkeypatch.setattr(sys, "stderr", fake_stderr)

        from provide.telemetry.config import TelemetryConfig

        cfg = TelemetryConfig.from_env({"PROVIDE_LOG_FORMAT": "pretty", "PROVIDE_LOG_INCLUDE_CALLER": "false"})
        configure_logging(cfg)  # must not raise

        bound = structlog.get_logger("test_pretty")
        bound.info("auth.login.complete", user_id="u1")

        output = fake_stderr.getvalue()
        assert "\033" in output  # ANSI codes present when isatty=True

    def test_configure_logging_pretty_no_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _reset_logging_for_tests()

        class _FakeNonTTY(io.StringIO):
            def isatty(self) -> bool:
                return False

        fake_stderr = _FakeNonTTY()
        monkeypatch.setattr(sys, "stderr", fake_stderr)

        from provide.telemetry.config import TelemetryConfig

        cfg = TelemetryConfig.from_env({"PROVIDE_LOG_FORMAT": "pretty", "PROVIDE_LOG_INCLUDE_CALLER": "false"})
        configure_logging(cfg)

        bound = structlog.get_logger("test_pretty_notty")
        bound.info("auth.login.complete")

        output = fake_stderr.getvalue()
        assert "\033" not in output  # no ANSI codes when not a TTY

    def test_configure_logging_pretty_key_color_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        structlog.reset_defaults()
        _reset_logging_for_tests()

        class _FakeTTY(io.StringIO):
            def isatty(self) -> bool:
                return True

        fake_stderr = _FakeTTY()
        monkeypatch.setattr(sys, "stderr", fake_stderr)

        from provide.telemetry.config import TelemetryConfig

        cfg = TelemetryConfig.from_env(
            {
                "PROVIDE_LOG_FORMAT": "pretty",
                "PROVIDE_LOG_PRETTY_KEY_COLOR": "cyan",
                "PROVIDE_LOG_INCLUDE_CALLER": "false",
            }
        )
        configure_logging(cfg)

        bound = structlog.get_logger("test_pretty_key_color")
        bound.info("auth.login.complete", user_id="u1")

        output = fake_stderr.getvalue()
        assert NAMED_COLORS["cyan"] in output

    def test_configure_logging_pretty_fields_filter_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        structlog.reset_defaults()
        _reset_logging_for_tests()

        class _FakeTTY(io.StringIO):
            def isatty(self) -> bool:
                return True

        fake_stderr = _FakeTTY()
        monkeypatch.setattr(sys, "stderr", fake_stderr)

        from provide.telemetry.config import TelemetryConfig

        cfg = TelemetryConfig.from_env(
            {
                "PROVIDE_LOG_FORMAT": "pretty",
                "PROVIDE_LOG_PRETTY_FIELDS": "user_id",
                "PROVIDE_LOG_INCLUDE_CALLER": "false",
            }
        )
        configure_logging(cfg)

        bound = structlog.get_logger("test_pretty_fields")
        bound.info("auth.login.complete", user_id="u1", secret="s3cr3t")

        output = fake_stderr.getvalue()
        assert "user_id" in output
        assert "secret" not in output


# ---------------------------------------------------------------------------
# TestPrettyRendererKVColors
# ---------------------------------------------------------------------------


class TestPrettyRendererKVColors:
    def test_key_color_applied(self) -> None:
        cyan = NAMED_COLORS["cyan"]
        d = _base()
        d["mykey"] = "myval"
        output = _make(d, key_color=cyan)
        assert cyan + "mykey" + RESET in output

    def test_value_color_applied(self) -> None:
        blue = NAMED_COLORS["blue"]
        d = _base()
        d["mykey"] = "myval"
        output = _make(d, value_color=blue)
        assert blue + repr("myval") + RESET in output

    def test_no_key_color_when_empty(self) -> None:
        d = _base()
        d["mykey"] = "myval"
        output = _make(d, key_color="")
        # key appears without any ANSI prefix
        assert "mykey=" in output
        idx = output.index("mykey=")
        assert output[idx - 1] != "\033"

    def test_no_value_color_when_empty(self) -> None:
        d = _base()
        d["mykey"] = "myval"
        output = _make(d, value_color="")
        assert "='myval'" in output

    def test_kv_colors_suppressed_when_colors_false(self) -> None:
        cyan = NAMED_COLORS["cyan"]
        blue = NAMED_COLORS["blue"]
        d = _base()
        d["mykey"] = "myval"
        output = _make(d, colors=False, key_color=cyan, value_color=blue)
        assert cyan not in output
        assert blue not in output


# ---------------------------------------------------------------------------
# TestPrettyRendererFieldFilter
# ---------------------------------------------------------------------------


class TestPrettyRendererFieldFilter:
    def test_fields_allowlist_includes_only_specified(self) -> None:
        d = _base()
        d["foo"] = "x"
        d["bar"] = "y"
        output = _make(d, colors=False, fields=("foo",))
        assert "foo=" in output
        assert "bar=" not in output

    def test_fields_allowlist_empty_shows_all(self) -> None:
        d = _base()
        d["foo"] = "x"
        d["bar"] = "y"
        output = _make(d, colors=False, fields=())
        assert "foo=" in output
        assert "bar=" in output

    def test_fields_allowlist_missing_key_omitted(self) -> None:
        d = _base()
        d["foo"] = "x"
        output = _make(d, colors=False, fields=("foo", "missing"))
        assert "foo=" in output
        assert "missing=" not in output

    def test_fields_allowlist_order_still_sorted(self) -> None:
        d = _base()
        d["zebra"] = 1
        d["apple"] = 2
        d["mango"] = 3
        output = _make(d, colors=False, fields=("zebra", "apple", "mango"))
        apple_pos = output.index("apple=")
        mango_pos = output.index("mango=")
        zebra_pos = output.index("zebra=")
        assert apple_pos < mango_pos < zebra_pos


# ---------------------------------------------------------------------------
# TestResolveColor
# ---------------------------------------------------------------------------


class TestResolveColor:
    def test_known_name_returns_escape(self) -> None:
        assert resolve_color("cyan") == NAMED_COLORS["cyan"]

    def test_empty_string_returns_empty(self) -> None:
        assert resolve_color("") == ""

    def test_unknown_name_returns_empty(self) -> None:
        assert resolve_color("fuchsia") == ""

    def test_none_name_returns_empty(self) -> None:
        assert resolve_color("none") == ""
