# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import logging
from typing import Any, cast

import pytest

from provide.telemetry.config import LoggingConfig, TelemetryConfig
from provide.telemetry.exceptions import ConfigurationError
from provide.telemetry.logger import core as core_mod
from provide.telemetry.logger.core import _reset_logging_for_tests


def test_configure_logging_tracks_active_config_and_level_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_logging_for_tests()

    seen_level: list[int] = []
    seen_sanitize: list[bool] = []
    configure_kwargs: dict[str, Any] = {}

    def _build_handlers(config: TelemetryConfig, level: int) -> list[logging.Handler]:
        _ = config
        seen_level.append(level)
        return [logging.StreamHandler()]

    def _sanitize_sensitive_fields(enabled: bool, max_depth: int = 8) -> Any:
        seen_sanitize.append(enabled)

        def _processor(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
            return event_dict

        return _processor

    def _configure(**kwargs: Any) -> None:
        configure_kwargs.update(kwargs)

    monkeypatch.setattr(core_mod, "_build_handlers", _build_handlers)
    monkeypatch.setattr(core_mod, "sanitize_sensitive_fields", _sanitize_sensitive_fields)
    core_mod_any = cast(Any, core_mod)
    structlog_mod: Any = core_mod_any.structlog
    monkeypatch.setattr(structlog_mod, "configure", _configure)

    cfg = TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": "WARNING", "PROVIDE_LOG_SANITIZE": "true"})
    core_mod.configure_logging(cfg)

    assert seen_level == [logging.WARNING]
    assert seen_sanitize == [True]
    assert "wrapper_class" in configure_kwargs and isinstance(configure_kwargs["wrapper_class"], type)
    assert "logger_factory" in configure_kwargs and callable(configure_kwargs["logger_factory"])
    assert core_mod._active_config == cfg
    assert core_mod._configured is True


def test_configure_logging_console_renderer_uses_colors_false(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_logging_for_tests()
    captured: list[bool | None] = []

    class _ConsoleRenderer:
        def __init__(self, *, colors: bool | None) -> None:
            captured.append(colors)

    core_mod_any = cast(Any, core_mod)
    structlog_mod: Any = core_mod_any.structlog
    monkeypatch.setattr(structlog_mod.dev, "ConsoleRenderer", _ConsoleRenderer)
    cfg = TelemetryConfig.from_env({"PROVIDE_LOG_FORMAT": "console"})
    core_mod.configure_logging(cfg)
    # In test environments, stderr is not a TTY so colors=False
    import sys

    assert captured == [sys.stderr.isatty()]


def test_fmt_pretty_is_valid() -> None:
    cfg = LoggingConfig(fmt="pretty")
    assert cfg.fmt == "pretty"


def test_fmt_invalid_still_rejects() -> None:
    with pytest.raises(ConfigurationError, match="invalid log format"):
        LoggingConfig(fmt="xml")


def test_from_env_pretty_format() -> None:
    cfg = TelemetryConfig.from_env({"PROVIDE_LOG_FORMAT": "pretty"})
    assert cfg.logging.fmt == "pretty"


def test_pretty_key_color_valid() -> None:
    cfg = LoggingConfig(pretty_key_color="cyan")
    assert cfg.pretty_key_color == "cyan"


def test_pretty_key_color_invalid() -> None:
    with pytest.raises(ConfigurationError, match="invalid color name for pretty_key_color"):
        LoggingConfig(pretty_key_color="fuchsia")


def test_pretty_value_color_invalid() -> None:
    with pytest.raises(ConfigurationError, match="invalid color name for pretty_value_color"):
        LoggingConfig(pretty_value_color="fuchsia")


def test_pretty_key_color_empty_is_valid() -> None:
    cfg = LoggingConfig(pretty_key_color="")
    assert cfg.pretty_key_color == ""


def test_from_env_pretty_colors_and_fields() -> None:
    cfg = TelemetryConfig.from_env(
        {
            "PROVIDE_LOG_PRETTY_KEY_COLOR": "cyan",
            "PROVIDE_LOG_PRETTY_VALUE_COLOR": "blue",
            "PROVIDE_LOG_PRETTY_FIELDS": "user_id, session_id",
        }
    )
    assert cfg.logging.pretty_key_color == "cyan"
    assert cfg.logging.pretty_value_color == "blue"
    assert cfg.logging.pretty_fields == ("user_id", "session_id")
