# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Health and release sit where spec/pipeline_fixtures.yaml puts them.

Admission (consent, sampling, backpressure) counts drops and releases on every
refusal; an admitted record is counted emitted only at the handler boundary,
after the local and backend children, and hardening -- now after admission --
never loses the ticket the record carries.
"""

from __future__ import annotations

import logging

import pytest
import structlog

from provide.telemetry import backpressure
from provide.telemetry.backpressure import QueuePolicy, QueueTicket, set_queue_policy, try_acquire
from provide.telemetry.consent import ConsentLevel, set_consent_level
from provide.telemetry.health import get_health_snapshot, reset_health_for_tests
from provide.telemetry.logger.handlers import _BackpressureFanoutHandler
from provide.telemetry.logger.processors import (
    _BACKPRESSURE_TICKET_KEY,
    _PIPELINE_RECORD_KEY,
    _PIPELINE_RECORD_MARKER,
    apply_sampling,
    harden_input,
)
from provide.telemetry.sampling import SamplingPolicy, set_sampling_policy


@pytest.fixture(autouse=True)
def _fresh_health() -> None:
    reset_health_for_tests()


def _released(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    calls: list[object] = []
    real = backpressure.release

    def _release(ticket: QueueTicket | None) -> None:
        calls.append(ticket)
        real(ticket)

    monkeypatch.setattr(backpressure, "release", _release)
    return calls


# ── admission ─────────────────────────────────────────────────────────────────


def test_a_consent_refusal_counts_one_drop_and_releases(monkeypatch: pytest.MonkeyPatch) -> None:
    released = _released(monkeypatch)
    set_consent_level(ConsentLevel.NONE)
    with pytest.raises(structlog.DropEvent):
        apply_sampling(None, "info", {"event": "a.b.c"})
    snapshot = get_health_snapshot()
    assert (snapshot.dropped_logs, snapshot.emitted_logs) == (1, 0)
    assert released == [None]


def test_a_sampling_refusal_counts_one_drop_and_releases(monkeypatch: pytest.MonkeyPatch) -> None:
    released = _released(monkeypatch)
    set_sampling_policy("logs", SamplingPolicy(default_rate=0.0))
    with pytest.raises(structlog.DropEvent):
        apply_sampling(None, "info", {"event": "a.b.c"})
    snapshot = get_health_snapshot()
    assert (snapshot.dropped_logs, snapshot.emitted_logs) == (1, 0)
    assert released == [None]


def test_a_queue_refusal_counts_one_drop_and_releases(monkeypatch: pytest.MonkeyPatch) -> None:
    set_queue_policy(QueuePolicy(logs_maxsize=1))
    held = try_acquire("logs")
    released = _released(monkeypatch)
    with pytest.raises(structlog.DropEvent):
        apply_sampling(None, "info", {"event": "a.b.c"})
    snapshot = get_health_snapshot()
    assert (snapshot.dropped_logs, snapshot.emitted_logs) == (1, 0)
    assert released == [None]
    backpressure.release(held)


def test_admission_counts_nothing_and_releases_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    released = _released(monkeypatch)
    result = apply_sampling(None, "info", {"event": "a.b.c"})
    snapshot = get_health_snapshot()
    assert (snapshot.dropped_logs, snapshot.emitted_logs) == (0, 0)
    assert released == []
    assert isinstance(result[_BACKPRESSURE_TICKET_KEY], QueueTicket)


# ── hardening after admission ─────────────────────────────────────────────────


def test_hardening_keeps_the_ticket_outside_the_attribute_budget() -> None:
    ticket = QueueTicket(signal="logs", token=7)
    processor = harden_input(1024, 2, 8)
    result = processor(None, "info", {"event": "e", "a": 1, "b": 2, _BACKPRESSURE_TICKET_KEY: ticket})
    assert result[_BACKPRESSURE_TICKET_KEY] is ticket
    # The budget of two went to the caller's fields, not to the ticket.
    assert {key for key in result if key != _BACKPRESSURE_TICKET_KEY} == {"event", "a"}


def test_hardening_without_a_ticket_adds_none() -> None:
    result = harden_input(1024, 0, 8)(None, "info", {"event": "e"})
    assert result == {"event": "e"}


# ── the handler boundary ──────────────────────────────────────────────────────


class _Order(logging.Handler):
    def __init__(self, order: list[str], name: str) -> None:
        super().__init__()
        self._order = order
        self._name = name

    def emit(self, record: logging.LogRecord) -> None:
        self._order.append(f"{self._name}:emitted={get_health_snapshot().emitted_logs}")


def _record(*, marked: bool, ticket: QueueTicket | None) -> logging.LogRecord:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "m", None, None)
    if marked:
        record.__dict__[_PIPELINE_RECORD_KEY] = _PIPELINE_RECORD_MARKER
    if ticket is not None:
        record.__dict__[_BACKPRESSURE_TICKET_KEY] = ticket
    return record


def test_an_admitted_record_is_counted_after_both_children_and_before_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    real = backpressure.release

    def _release(ticket: QueueTicket | None) -> None:
        order.append(f"release:emitted={get_health_snapshot().emitted_logs}")
        real(ticket)

    monkeypatch.setattr(backpressure, "release", _release)
    fanout = _BackpressureFanoutHandler([_Order(order, "local"), _Order(order, "backend")])
    fanout.handle(_record(marked=True, ticket=QueueTicket(signal="logs", token=0)))
    assert order == ["local:emitted=0", "backend:emitted=0", "release:emitted=1"]


@pytest.mark.parametrize(
    ("marked", "ticket"),
    [(False, QueueTicket(signal="logs", token=0)), (True, None), (False, None)],
    ids=["foreign-with-forged-ticket", "marked-without-ticket", "foreign"],
)
def test_only_an_admitted_record_is_counted(marked: bool, ticket: QueueTicket | None) -> None:
    _BackpressureFanoutHandler([logging.NullHandler()]).handle(_record(marked=marked, ticket=ticket))
    assert get_health_snapshot().emitted_logs == 0


def test_a_child_that_raises_is_not_counted_but_still_releases(monkeypatch: pytest.MonkeyPatch) -> None:
    released = _released(monkeypatch)

    class _Raises(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            raise RuntimeError("escaped")

        def handle(self, record: logging.LogRecord) -> bool:
            self.emit(record)
            return True

    ticket = QueueTicket(signal="logs", token=0)
    with pytest.raises(RuntimeError, match="escaped"):
        _BackpressureFanoutHandler([_Raises()]).emit(_record(marked=True, ticket=ticket))
    assert get_health_snapshot().emitted_logs == 0
    assert released == [ticket]
