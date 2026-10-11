# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Stdlib logging handlers used by the structlog pipeline."""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from provide.telemetry.logger._foreign_records import sanitize_foreign_record
from provide.telemetry.logger.processors import (
    _BACKPRESSURE_TICKET_KEY,
    _PIPELINE_RECORD_KEY,
    _PIPELINE_RECORD_MARKER,
)
from provide.telemetry.logger.sink import WRITER_FRAME


class LogWriterReenteredError(RuntimeError):
    """A record logged from inside the log output writer, on the thread writing to it."""


_REENTERED = LogWriterReenteredError("record logged from inside the log output writer was dropped")


def _count_export_failure(exc: Exception) -> None:
    # Imported on the failure path only, keeping it off every record's way through.
    from provide.telemetry.health import record_export_failure

    record_export_failure("logs", exc)


class _HostWriterHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """The console handler for a writer the host installed with ``set_log_output``.

    Two things differ from the ``StreamHandler`` it extends, both because the
    writer is the host's code running inside a log call.

    A record logged from inside the writer, on the thread already writing to it,
    is not written: it would call the writer again, and that call would log
    again. It is counted as a log export failure instead, and the record being
    written is unaffected. A record from another thread is never refused; it
    waits for the handler's lock as it always has.

    A writer that raises costs only the record it was writing, counted as a log
    export failure, where ``StreamHandler`` hands it to ``handleError`` -- which
    prints a traceback, and the record with it, to stderr: the stream a host that
    installed a writer has said it is not reading.
    """

    def emit(self, record: logging.LogRecord) -> None:
        frame = WRITER_FRAME
        if frame.active:
            _count_export_failure(_REENTERED)
            return
        frame.active = True
        try:
            self.stream.write(self.format(record) + self.terminator)
            logging.StreamHandler.flush(self)
        except Exception as exc:
            _count_export_failure(exc)
        finally:
            frame.active = False

    def flush(self) -> None:
        """Flush the writer, unless this thread is already inside it.

        A writer whose ``write`` reaches a flush of this handler -- through
        ``logging.shutdown`` or a reconfiguration -- would otherwise call back
        into itself. A flush that raises still raises, as it does from a
        ``StreamHandler``; teardown is where flushes happen, and it decides.
        """
        frame = WRITER_FRAME
        if frame.active:
            return
        frame.active = True
        try:
            logging.StreamHandler.flush(self)
        finally:
            frame.active = False


# The children a retarget moves: the plain console handler and the one wrapping
# a host's writer. Exact types, so a FileHandler -- a StreamHandler by
# inheritance -- keeps the file it owns.
_STREAM_CHILDREN = (logging.StreamHandler, _HostWriterHandler)


class _BackpressureFanoutHandler(logging.Handler):
    """Fan out a LogRecord to child handlers and release the ticket after all emit."""

    def __init__(self, handlers: list[logging.Handler]) -> None:
        min_level = min((handler.level for handler in handlers), default=logging.NOTSET)
        logging.Handler.__init__(self, level=min_level)
        self._handlers = handlers

        existing_formatter = next((handler.formatter for handler in handlers if handler.formatter is not None), None)
        if existing_formatter is not None:
            logging.Handler.setFormatter(self, existing_formatter)

    def setFormatter(self, fmt: logging.Formatter | None) -> None:
        super().setFormatter(fmt)
        for handler in self._handlers:
            if handler.formatter is None:
                handler.setFormatter(fmt)

    def replace_children(self, handlers: list[logging.Handler]) -> None:
        """Swap the child handlers in place, closing the ones replaced.

        This is what lets a reload rebuild the pipeline without touching the
        root logger's handler list. Reconfiguring through
        ``basicConfig(force=True)`` a second time would remove and close every
        root handler, including any the host installed after setup — and Python
        is the SDK whose whole redirection story is that the host uses the
        stdlib's own mechanism.

        Each rebuild constructs fresh child handlers, so the outgoing ones are
        never also incoming and closing them is unconditional — the same
        close ``basicConfig(force=True)`` used to perform through this
        handler's own ``close()``.
        """
        previous = self._handlers
        self._handlers = handlers
        self.setLevel(min((handler.level for handler in handlers), default=logging.NOTSET))
        if self.formatter is not None:
            self.setFormatter(self.formatter)
        for handler in previous:
            handler.close()

    def retarget_stream_children(self, stream: Any) -> None:
        """Point the plain stream children at *stream*, leaving the rest alone.

        A released writer is not enough on its own: a child handler took the
        writer when it was built and goes on holding it, so a host told its
        writer had been let go could close it and still have records arrive.
        Retargeting is narrower than a rebuild, which would reconstruct the OTLP
        child and its provider on the way out of a teardown that exists to
        dismantle them.

        Only the console children are moved -- an exact ``StreamHandler``, or the
        handler wrapping a host's writer. A ``FileHandler`` is a ``StreamHandler``
        by inheritance and owns a file of its own to write to, which is not this
        SDK's to redirect.

        The stream is assigned rather than handed to ``setStream``, which flushes
        the outgoing one first. That stream belongs to the host, a host told its
        writer has been let go is entitled to have closed it, and flushing a
        closed file raises before the swap -- leaving the child on exactly the
        dead stream this call exists to move it off. A live stream is still owed
        its flush, so the flush is attempted and only its failure ignored.
        """
        for handler in self._handlers:
            if not isinstance(handler, logging.StreamHandler) or type(handler) not in _STREAM_CHILDREN:
                continue
            handler.acquire()
            try:
                with contextlib.suppress(Exception):
                    handler.flush()
                handler.stream = stream
            finally:
                handler.release()

    def emit(self, record: logging.LogRecord) -> None:
        from provide.telemetry.backpressure import release
        from provide.telemetry.health import increment_emitted

        # Popped, not read: the ticket is ours, and OTel's LoggingHandler turns
        # whatever is left on the record into OTLP attributes. Reading it with
        # getattr left it in place for the duration of the fan-out, which
        # exported __provide_telemetry_backpressure_ticket__ on every record
        # that reached a collector. Lifting it here keeps it alive for the
        # release below while hiding it from every child handler at once.
        ticket = record.__dict__.pop(_BACKPRESSURE_TICKET_KEY, None)
        # A record without the pipeline's marker came from a plain stdlib
        # logger and never ran the processor chain; the children get a
        # hardened, sanitized copy of it instead. Popped for the same reason
        # as the ticket: nothing of ours is exported as an attribute.
        admitted = record.__dict__.pop(_PIPELINE_RECORD_KEY, None) is _PIPELINE_RECORD_MARKER
        if not admitted:
            record = sanitize_foreign_record(record)
        try:
            for handler in self._handlers:
                if record.levelno >= handler.level:
                    handler.handle(record)
            # The health stage: after the local and backend sinks, before the
            # release (spec/pipeline_fixtures.yaml). A backend that failed to
            # export still counts -- its handler contained the failure and
            # recorded it as an export failure -- but only a record the
            # pipeline admitted, and so holds a ticket, is one it emitted.
            if admitted and ticket is not None:
                increment_emitted("logs")
        finally:
            if ticket is not None:
                release(ticket)

    def flush(self) -> None:
        for handler in self._handlers:
            handler.flush()

    def close(self) -> None:
        try:
            for handler in self._handlers:
                handler.close()
        finally:
            super().close()
