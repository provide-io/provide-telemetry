# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

import logging
from typing import Any, cast

import pytest

from undef.telemetry.config import TelemetryConfig
from undef.telemetry.logger import core as core_mod


def test_configure_logging_tracks_active_config_and_level_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    core_mod._configured = False
    core_mod._active_config = None

    seen_level: list[int] = []
    seen_sanitize: list[bool] = []
    configure_kwargs: dict[str, Any] = {}

    def _build_handlers(config: TelemetryConfig, level: int) -> list[logging.Handler]:
        _ = config
        seen_level.append(level)
        return [logging.StreamHandler()]

    def _sanitize_sensitive_fields(enabled: bool) -> Any:
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

    cfg = TelemetryConfig.from_env({"UNDEF_LOG_LEVEL": "WARNING", "UNDEF_LOG_SANITIZE": "true"})
    core_mod.configure_logging(cfg)

    assert seen_level == [logging.WARNING]
    assert seen_sanitize == [True]
    assert "wrapper_class" in configure_kwargs and configure_kwargs["wrapper_class"] is not None
    assert "logger_factory" in configure_kwargs and configure_kwargs["logger_factory"] is not None
    assert core_mod._active_config == cfg
    assert core_mod._configured is True


def test_configure_logging_console_renderer_uses_colors_false(monkeypatch: pytest.MonkeyPatch) -> None:
    core_mod._configured = False
    core_mod._active_config = None
    captured: list[bool | None] = []

    class _ConsoleRenderer:
        def __init__(self, *, colors: bool | None) -> None:
            captured.append(colors)

    core_mod_any = cast(Any, core_mod)
    structlog_mod: Any = core_mod_any.structlog
    monkeypatch.setattr(structlog_mod.dev, "ConsoleRenderer", _ConsoleRenderer)
    cfg = TelemetryConfig.from_env({"UNDEF_LOG_FORMAT": "console"})
    core_mod.configure_logging(cfg)
    assert captured == [False]
