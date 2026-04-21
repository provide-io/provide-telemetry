# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Targeted mutation-kill tests for the _BackpressureFanoutHandler class.

Each test pins a specific observable behaviour of the handler so a mutation
that changes it gets caught. See `src/provide/telemetry/logger/handlers.py`.
"""

from __future__ import annotations

import logging

from provide.telemetry.backpressure import QueueTicket
from provide.telemetry.logger.handlers import _BackpressureFanoutHandler
from provide.telemetry.logger.processors import _BACKPRESSURE_TICKET_KEY


def _make_record(
    level: int = logging.INFO,
    extra: dict[str, object] | None = None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test",
        level=level,
        pathname=__file__,
        lineno=1,
        msg="msg",
        args=None,
        exc_info=None,
    )
    if extra is not None:
        for k, v in extra.items():
            setattr(record, k, v)
    return record


def test_fanout_level_is_min_of_children_not_notset() -> None:
    """Mutant: `logging.Handler.__init__(self)` drops level=min_level → level defaults to NOTSET.

    Pin the behaviour: fanout level must equal the minimum of child levels.
    """
    low = logging.Handler(level=logging.DEBUG)
    high = logging.Handler(level=logging.ERROR)
    fanout = _BackpressureFanoutHandler([low, high])
    assert fanout.level == logging.DEBUG
    assert fanout.level != logging.NOTSET


def test_fanout_emit_removes_ticket_attribute_from_record_after_release() -> None:
    """Mutant: `delattr(None, _BACKPRESSURE_TICKET_KEY)` leaves the attribute
    on the record (AttributeError on None is suppressed, but the delattr on
    the real record never happens). Pin: after emit, the record no longer
    carries the ticket attribute."""
    child = logging.Handler(level=logging.DEBUG)
    child.emit = lambda _r: None  # type: ignore[assignment,method-assign]
    fanout = _BackpressureFanoutHandler([child])

    ticket = QueueTicket(signal="logs", token=0)  # token=0 → unlimited-queue sentinel (release is a no-op)
    record = _make_record(extra={_BACKPRESSURE_TICKET_KEY: ticket})
    assert hasattr(record, _BACKPRESSURE_TICKET_KEY)
    fanout.emit(record)
    assert not hasattr(record, _BACKPRESSURE_TICKET_KEY), "emit() must remove the ticket attribute from the record"


def test_fanout_emit_suppresses_attribute_error_from_delattr() -> None:
    """Mutant: `suppress(None)` instead of `suppress(AttributeError)` — if
    delattr raises AttributeError, `suppress(None)` propagates TypeError from
    its own __exit__ (because issubclass(AttributeError, None) fails). Pin:
    emit() must not raise when delattr raises AttributeError.
    """

    class _RecordBlockingDelete(logging.LogRecord):
        def __delattr__(self, name: str) -> None:
            if name == _BACKPRESSURE_TICKET_KEY:
                raise AttributeError(f"cannot delete {name}")
            super().__delattr__(name)

    child = logging.Handler(level=logging.DEBUG)
    child.emit = lambda _r: None  # type: ignore[assignment,method-assign]
    fanout = _BackpressureFanoutHandler([child])

    ticket = QueueTicket(signal="logs", token=0)
    record = _RecordBlockingDelete(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="msg",
        args=None,
        exc_info=None,
    )
    setattr(record, _BACKPRESSURE_TICKET_KEY, ticket)
    fanout.emit(record)  # must not raise — real code suppresses AttributeError
