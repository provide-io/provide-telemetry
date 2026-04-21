# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Kill surviving mutants in ``logger/core.py`` for the OTLP logs setup path.

Targets ``_build_handlers`` and ``_make_otel_logging_handler``. The tests run
the real code path end-to-end with fake OTel components whose constructors
capture every argument they receive, so each mutation (argument swap, keyword
rename, dict-key text mutation, etc.) is detectable as a concrete assertion
failure.
"""

from __future__ import annotations

import logging
import warnings
from types import SimpleNamespace
from typing import Any, cast

import pytest

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger import core as core_mod
from provide.telemetry.logger.core import _reset_logging_for_tests


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Reset module-level singletons so one test can't leak into another."""
    _reset_logging_for_tests()


# _make_otel_logging_handler — both branches, every kwarg.
# ─────────────────────────────────────────────────────────────────────────────


class TestMakeOtelLoggingHandlerInstrumentationBranch:
    """Kill mutants targeting the instrumentation-handler construction block.

    * mutmut_1: instrumentation_handler_cls = None  → falls through to SDK path
    * mutmut_3: level=None in ctor kwargs           → handler.level ends up 0/None
    * mutmut_4: logger_provider=None                → handler.logger_provider is None
    * mutmut_5: log_code_attributes=None            → handler.log_code_attributes is None
    * mutmut_6/7/8: kwarg omitted entirely          → TypeError or missing attribute
    """

    def _build_handler_cls(self) -> type[logging.Handler]:
        class _InstrumentationHandler(logging.Handler):
            def __init__(
                self,
                *,
                level: int,
                logger_provider: object,
                log_code_attributes: bool,
            ) -> None:
                # Strict kwargs — omitting any raises TypeError, which kills
                # the "missing kwarg" mutants (mutmut_6/7/8).
                super().__init__(level=level)
                self.logger_provider = logger_provider
                self.log_code_attributes = log_code_attributes

        return _InstrumentationHandler

    def test_instrumentation_branch_propagates_all_three_kwargs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills mutmut_1, 3, 4, 5, 6, 7, 8."""
        handler_cls = self._build_handler_cls()
        monkeypatch.setattr(core_mod, "_load_instrumentation_logging_handler", lambda: handler_cls)

        cfg = TelemetryConfig.from_env({"PROVIDE_LOG_CODE_ATTRIBUTES": "true"})
        provider = object()
        sdk_logs_mod = SimpleNamespace()  # unused on this branch

        raw = core_mod._make_otel_logging_handler(sdk_logs_mod, provider, logging.WARNING, cfg)
        assert isinstance(raw, handler_cls)
        # level=level (kills mutmut_3 level=None)
        assert raw.level == logging.WARNING
        # logger_provider=provider (kills mutmut_4 logger_provider=None)
        assert getattr(raw, "logger_provider") is provider  # noqa: B009
        # log_code_attributes=config.logging.log_code_attributes (kills mutmut_5)
        assert getattr(raw, "log_code_attributes") is True  # noqa: B009

    def test_instrumentation_branch_propagates_false_log_code_attributes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ensure the log_code_attributes=None mutation (mutmut_5) is detected
        when the config value is False — ``None`` and ``False`` are both falsy
        under ``is`` only one way, so we check both truthy and falsy cases.
        """
        handler_cls = self._build_handler_cls()
        monkeypatch.setattr(core_mod, "_load_instrumentation_logging_handler", lambda: handler_cls)
        cfg = TelemetryConfig()  # defaults: log_code_attributes=False
        handler = cast(
            Any,
            core_mod._make_otel_logging_handler(SimpleNamespace(), object(), logging.INFO, cfg),
        )
        assert handler.log_code_attributes is False, "log_code_attributes must be the real False, not None"

    def test_instrumentation_branch_not_taken_when_loader_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """mutmut_1 makes the instrumentation_handler_cls always None; the
        branch is then never taken. The test below (SDK fallback) already
        asserts that the SDK path works, but we additionally assert that when
        ``_load_instrumentation_logging_handler`` truly returns None, the SDK
        ``LoggingHandler`` is what's built — this pins the ``is not None``
        check rather than its negation.
        """
        monkeypatch.setattr(core_mod, "_load_instrumentation_logging_handler", lambda: None)

        class _SDKHandler(logging.Handler):
            def __init__(self, level: int, logger_provider: object) -> None:
                super().__init__(level=level)
                self.logger_provider = logger_provider

        sdk_logs_mod = SimpleNamespace(LoggingHandler=_SDKHandler)
        handler = core_mod._make_otel_logging_handler(sdk_logs_mod, object(), logging.DEBUG, TelemetryConfig())
        assert isinstance(handler, _SDKHandler)


class TestMakeOtelLoggingHandlerSdkFallbackBranch:
    """Kill mutants targeting the SDK fallback (warnings + LoggingHandler)."""

    def test_sdk_handler_receives_real_level_and_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The SDK ``LoggingHandler`` must receive the real level/provider."""
        monkeypatch.setattr(core_mod, "_load_instrumentation_logging_handler", lambda: None)

        class _SDKHandler(logging.Handler):
            def __init__(self, level: int, logger_provider: object) -> None:
                super().__init__(level=level)
                self.logger_provider = logger_provider

        sdk_logs_mod = SimpleNamespace(LoggingHandler=_SDKHandler)
        sentinel_provider = object()
        handler = cast(
            Any,
            core_mod._make_otel_logging_handler(sdk_logs_mod, sentinel_provider, logging.ERROR, TelemetryConfig()),
        )
        assert handler.level == logging.ERROR
        assert handler.logger_provider is sentinel_provider

    def test_sdk_fallback_filters_deprecation_warnings_specifically(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``warnings.simplefilter`` must be called with ``("ignore", DeprecationWarning)``.

        Kills mutmut_10 (category=None) and mutmut_12 (category kwarg omitted).
        """
        monkeypatch.setattr(core_mod, "_load_instrumentation_logging_handler", lambda: None)

        class _SDKHandler(logging.Handler):
            def __init__(self, level: int, logger_provider: object) -> None:
                super().__init__(level=level)

        sdk_logs_mod = SimpleNamespace(LoggingHandler=_SDKHandler)

        captured: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def _capture_simplefilter(*args: object, **kwargs: object) -> None:
            captured.append((args, kwargs))

        monkeypatch.setattr(warnings, "simplefilter", _capture_simplefilter)

        core_mod._make_otel_logging_handler(sdk_logs_mod, object(), logging.INFO, TelemetryConfig())

        assert captured, "warnings.simplefilter must be called"
        args, kwargs = captured[0]
        assert args == ("ignore", DeprecationWarning), (
            f"simplefilter must receive ('ignore', DeprecationWarning) — got args={args!r} "
            f"kwargs={kwargs!r} (kills mutmut_10 category=None and mutmut_12 missing category)"
        )
