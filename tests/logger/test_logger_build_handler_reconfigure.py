# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from provide.telemetry import resilience as resilience_mod
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger import core as core_mod
from provide.telemetry.logger.core import _reset_logging_for_tests


@pytest.fixture(autouse=True)
def _bypass_resilience(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resilience_mod, "run_with_resilience", lambda _signal, op: op())


def test_build_handlers_reuses_existing_provider_for_safe_logging_reconfigure(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_logging_for_tests()
    base_cfg = TelemetryConfig.from_env(
        {
            "PROVIDE_TELEMETRY_SERVICE_NAME": "svc",
            "PROVIDE_TELEMETRY_VERSION": "1.0.0",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs",
        }
    )
    next_cfg = TelemetryConfig.from_env(
        {
            "PROVIDE_TELEMETRY_SERVICE_NAME": "svc",
            "PROVIDE_TELEMETRY_VERSION": "1.0.0",
            "PROVIDE_LOG_LEVEL": "DEBUG",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs",
        }
    )

    class _Provider:
        pass

    class _LoggingHandler(logging.Handler):
        def __init__(self, level: int, logger_provider: _Provider) -> None:
            super().__init__(level=level)
            self.logger_provider = logger_provider

    set_calls = {"count": 0}

    def _set_logger_provider(_provider: _Provider) -> None:
        set_calls["count"] += 1

    core_mod._active_config = base_cfg
    core_mod._otel_log_provider = _Provider()
    core_mod._otel_log_global_set = True
    monkeypatch.setattr(
        core_mod,
        "_load_otel_logs_components",
        lambda: (
            SimpleNamespace(set_logger_provider=_set_logger_provider),
            SimpleNamespace(LoggerProvider=object(), LoggingHandler=_LoggingHandler),
            SimpleNamespace(BatchLogRecordProcessor=object()),
            object(),
            object(),
        ),
    )
    monkeypatch.setattr(core_mod, "_load_instrumentation_logging_handler", lambda: None)

    handlers = core_mod._build_handlers(next_cfg, logging.DEBUG)
    assert len(handlers) == 2
    assert isinstance(handlers[1], _LoggingHandler)
    assert handlers[1].logger_provider is core_mod._otel_log_provider
    assert set_calls["count"] == 0
