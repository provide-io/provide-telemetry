# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""A ``set_log_output`` writer that logs back through the SDK.

``log_output`` in spec/telemetry-api.yaml: a record logged from inside the log
output writer, on the call stack already writing to it, is not written and
counts as an export failure; concurrent writers are never dropped.

Before the guard, Python did not deadlock -- the stdlib handler lock is an
``RLock`` -- it recursed: every nested record called the writer again, until
``RecursionError`` escaped the outermost log call with nothing written and
nothing counted. A writer that raised printed ``--- Logging error ---`` and the
record to stderr, and counted nothing either.
"""

from __future__ import annotations

import io
import logging
import threading
import time
from collections.abc import Callable, Iterator

import pytest
import structlog

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.health import get_health_snapshot
from provide.telemetry.logger.core import (
    clear_log_output,
    configure_logging,
    set_log_output,
    shutdown_logging,
)
from provide.telemetry.logger.handlers import _HostWriterHandler
from provide.telemetry.logger.sink import WRITER_FRAME


def _within_deadline(fn: Callable[[], None]) -> None:
    """Run *fn* on a thread and fail if it neither returns nor raises in time.

    The visible form of a deadlock, rather than a hung suite. An exception the
    call raised -- ``RecursionError`` was the old behaviour -- fails the test.
    """
    failure: list[BaseException] = []

    def run() -> None:
        try:
            fn()
        except BaseException as exc:  # pragma: no cover - reached only by a regression
            failure.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(10)
    assert not worker.is_alive(), "deadlocked: the call did not return"
    assert not failure, f"the call raised {failure[0]!r}"


class _CallbackWriter(io.StringIO):
    """Runs ``on_write`` from inside ``write``, as a writer reporting its own trouble would."""

    def __init__(self, on_write: Callable[[], None]) -> None:
        super().__init__()
        self.on_write = on_write

    def write(self, text: str) -> int:
        self.on_write()
        return super().write(text)


@pytest.fixture(autouse=True)
def _release_writer() -> Iterator[None]:
    yield
    clear_log_output()


def _configure(fmt: str) -> None:
    configure_logging(TelemetryConfig.from_env({"PROVIDE_LOG_FORMAT": fmt}), force=True)


@pytest.mark.parametrize("fmt", ["json", "console", "pretty"])
def test_a_writer_that_logs_back_is_neither_recursed_into_nor_shown_its_record(fmt: str) -> None:
    writer = _CallbackWriter(lambda: structlog.get_logger("writer").error("writer.reports.trouble"))
    set_log_output(writer)
    _configure(fmt)
    before = get_health_snapshot()

    _within_deadline(lambda: structlog.get_logger("probe").info("outer.record"))

    after = get_health_snapshot()
    assert after.export_failures_logs - before.export_failures_logs == 1
    # The nested record passed every admission gate, so it is emitted too:
    # health counts after the sinks, and a sink that failed still ran.
    assert after.emitted_logs - before.emitted_logs == 2
    assert "outer.record" in writer.getvalue()
    assert "writer.reports.trouble" not in writer.getvalue()
    assert WRITER_FRAME.active is False


def test_a_writer_that_logs_back_through_stdlib_logging_is_caught_too() -> None:
    """A third-party record reaches the same handler through the root fan-out."""
    writer = _CallbackWriter(lambda: logging.getLogger("third_party").error("writer.stdlib"))
    set_log_output(writer)
    _configure("json")
    before = get_health_snapshot()

    _within_deadline(lambda: structlog.get_logger("probe").info("outer.record"))

    after = get_health_snapshot()
    assert after.export_failures_logs - before.export_failures_logs == 1
    # A foreign record never ran the pipeline's admission, so only the outer
    # record is one the SDK emitted.
    assert after.emitted_logs - before.emitted_logs == 1
    assert "outer.record" in writer.getvalue()
    assert "writer.stdlib" not in writer.getvalue()


def test_the_handler_takes_the_next_record_after_refusing_one() -> None:
    calls: list[int] = []

    def report_once() -> None:
        if not calls:
            calls.append(1)
            structlog.get_logger("writer").error("nested")

    writer = _CallbackWriter(report_once)
    set_log_output(writer)
    _configure("json")

    _within_deadline(lambda: structlog.get_logger("probe").info("first"))
    structlog.get_logger("probe").info("second")

    assert "first" in writer.getvalue()
    assert "second" in writer.getvalue()
    assert "nested" not in writer.getvalue()


def test_a_writer_that_raises_costs_only_its_record_and_is_counted(capsys: pytest.CaptureFixture[str]) -> None:
    class _BrokenPipe(io.StringIO):
        def write(self, text: str) -> int:
            raise BrokenPipeError("host closed the pipe")

    set_log_output(_BrokenPipe())
    _configure("json")
    before = get_health_snapshot()

    structlog.get_logger("probe").info("lost.record")

    after = get_health_snapshot()
    assert after.export_failures_logs - before.export_failures_logs == 1
    assert after.emitted_logs - before.emitted_logs == 1
    # Not handed to handleError, which would print the record to stderr.
    assert "lost.record" not in capsys.readouterr().err
    assert WRITER_FRAME.active is False


class _SlowWriter(io.StringIO):
    """Widens the window in which a write is in progress, and asserts serialisation."""

    def __init__(self) -> None:
        super().__init__()
        self._busy = threading.Lock()
        self.overlapped = False

    def write(self, text: str) -> int:
        if not self._busy.acquire(blocking=False):
            self.overlapped = True
            return 0
        try:
            time.sleep(0)
            return super().write(text)
        finally:
            self._busy.release()


def test_concurrent_writers_wait_and_are_never_dropped() -> None:
    writer = _SlowWriter()
    set_log_output(writer)
    _configure("json")
    before = get_health_snapshot()
    threads, each = 8, 50

    def log_many() -> None:
        logger = structlog.get_logger("concurrent")
        for _ in range(each):
            logger.info("concurrent.record")

    workers = [threading.Thread(target=log_many) for _ in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(30)

    assert get_health_snapshot().export_failures_logs - before.export_failures_logs == 0
    assert writer.getvalue().count("concurrent.record") == threads * each
    assert writer.overlapped is False


def test_a_flush_reached_from_inside_the_writer_does_not_call_back_into_it() -> None:
    flushes: list[int] = []

    class _FlushingWriter(io.StringIO):
        handler: _HostWriterHandler | None = None

        def write(self, text: str) -> int:
            assert self.handler is not None
            self.handler.flush()
            return super().write(text)

        def flush(self) -> None:
            flushes.append(1)

    writer = _FlushingWriter()
    handler = _HostWriterHandler(writer)
    writer.handler = handler

    handler.emit(logging.makeLogRecord({"msg": "outer"}))

    # Once, from emit itself; the nested flush was refused.
    assert flushes == [1]
    handler.flush()
    assert flushes == [1, 1]


def test_a_flush_that_raises_still_raises_and_releases_the_frame() -> None:
    class _ClosedWriter(io.StringIO):
        def flush(self) -> None:
            raise ValueError("I/O operation on closed file")

    handler = _HostWriterHandler(_ClosedWriter())

    with pytest.raises(ValueError, match="closed file"):
        handler.flush()
    assert WRITER_FRAME.active is False


def test_a_writer_that_logs_from_its_flush_at_shutdown_does_not_recurse() -> None:
    class _ReportingFlush(io.StringIO):
        def flush(self) -> None:
            structlog.get_logger("writer").error("flush.trouble")

    writer = _ReportingFlush()
    set_log_output(writer)
    _configure("json")
    structlog.get_logger("probe").info("outer.record")

    _within_deadline(shutdown_logging)

    assert "outer.record" in writer.getvalue()
    assert "flush.trouble" not in writer.getvalue()
