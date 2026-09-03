# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Stdlib logging handlers used by the structlog pipeline."""

from __future__ import annotations

import logging

from provide.telemetry.logger.processors import _BACKPRESSURE_TICKET_KEY


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

    def emit(self, record: logging.LogRecord) -> None:
        from provide.telemetry.backpressure import release

        # Popped, not read: the ticket is ours, and OTel's LoggingHandler turns
        # whatever is left on the record into OTLP attributes. Reading it with
        # getattr left it in place for the duration of the fan-out, which
        # exported __provide_telemetry_backpressure_ticket__ on every record
        # that reached a collector. Lifting it here keeps it alive for the
        # release below while hiding it from every child handler at once.
        ticket = record.__dict__.pop(_BACKPRESSURE_TICKET_KEY, None)
        try:
            for handler in self._handlers:
                if record.levelno >= handler.level:
                    handler.handle(record)
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
