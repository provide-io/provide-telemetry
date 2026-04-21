# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import logging
import threading

import pytest

from provide.telemetry.backpressure import QueuePolicy, release, set_queue_policy, try_acquire
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger import core as core_mod
from provide.telemetry.logger import get_logger
from provide.telemetry.logger.core import _reset_logging_for_tests, configure_logging
from provide.telemetry.logger.handlers import _BackpressureFanoutHandler
from provide.telemetry.logger.processors import _BACKPRESSURE_TICKET_KEY
from provide.telemetry.pii import reset_pii_rules_for_tests
from provide.telemetry.sampling import SamplingPolicy, set_sampling_policy


@pytest.fixture(autouse=True)
def _reset_pii_rules() -> None:
    reset_pii_rules_for_tests()


def test_log_backpressure_ticket_stays_held_until_handler_emit_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_logging_for_tests()
    set_sampling_policy("logs", SamplingPolicy(default_rate=1.0))
    set_queue_policy(QueuePolicy(logs_maxsize=1))
    entered_emit = threading.Event()
    release_emit = threading.Event()

    class _BlockingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            _ = record
            entered_emit.set()
            assert release_emit.wait(timeout=2), "handler did not unblock in time"

    monkeypatch.setattr(core_mod, "_build_handlers", lambda _cfg, _lvl: [_BlockingHandler()])
    configure_logging(TelemetryConfig.from_env({"PROVIDE_LOG_FORMAT": "json"}))

    worker = threading.Thread(target=lambda: get_logger("blocked").info("test.backpressure.handler"))
    worker.start()
    assert entered_emit.wait(timeout=2), "handler did not start emitting"

    assert try_acquire("logs") is None, "log ticket must remain held while handler emit() is blocked"

    release_emit.set()
    worker.join(timeout=2)
    assert not worker.is_alive(), "log worker thread failed to finish"

    ticket = try_acquire("logs")
    assert ticket is not None, "log ticket must be released once handler emit() returns"
    release(ticket)


def test_backpressure_fanout_handler_releases_ticket_after_all_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    released: list[object] = []
    ticket = object()

    class _Child(logging.Handler):
        def __init__(self, level: int = logging.NOTSET) -> None:
            super().__init__(level=level)
            self.calls = 0

        def emit(self, record: logging.LogRecord) -> None:
            _ = record
            self.calls += 1

    child_info = _Child(logging.INFO)
    child_error = _Child(logging.ERROR)
    fanout = _BackpressureFanoutHandler([child_info, child_error])
    monkeypatch.setattr("provide.telemetry.backpressure.release", lambda t: released.append(t))

    record = logging.LogRecord("test", logging.INFO, __file__, 1, "msg", (), None)
    setattr(record, _BACKPRESSURE_TICKET_KEY, ticket)

    fanout.handle(record)

    assert child_info.calls == 1
    assert child_error.calls == 0
    assert released == [ticket]
