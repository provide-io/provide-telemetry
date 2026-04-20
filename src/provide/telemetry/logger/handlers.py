# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Stdlib logging handlers used by the structlog pipeline."""

from __future__ import annotations

import logging
from contextlib import suppress

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

    def setFormatter(self, fmt: logging.Formatter) -> None:
        super().setFormatter(fmt)
        for handler in self._handlers:
            if handler.formatter is None:
                handler.setFormatter(fmt)

    def emit(self, record: logging.LogRecord) -> None:
        from provide.telemetry.backpressure import release

        ticket = getattr(record, _BACKPRESSURE_TICKET_KEY, None)
        try:
            for handler in self._handlers:
                if record.levelno >= handler.level:
                    handler.handle(record)
        finally:
            if ticket is not None:
                release(ticket)
                with suppress(AttributeError):
                    delattr(record, _BACKPRESSURE_TICKET_KEY)

    def flush(self) -> None:
        for handler in self._handlers:
            handler.flush()

    def close(self) -> None:
        try:
            for handler in self._handlers:
                handler.close()
        finally:
            super().close()
