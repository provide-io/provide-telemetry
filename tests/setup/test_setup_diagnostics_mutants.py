# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests killing surviving mutants in setup.py's failure and shutdown paths.

Setup failure is the one moment an operator finds out telemetry is degraded, so
the rollback log must carry its traceback and the degraded-mode warning must be
blamed on the caller rather than on setup.py. shutdown's deadline has to reach
the drain or a SIGTERM handler's time budget is meaningless.

Covers:
  setup._rollback:          the rollback failure event name and its traceback
  setup.setup_telemetry:    degraded-mode warning category and stacklevel
  setup.shutdown_telemetry: the drain deadline is forwarded, not dropped
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest

from provide.telemetry import setup as setup_mod


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    setup_mod._reset_all_for_tests()
    yield
    setup_mod._reset_all_for_tests()


def test_rollback_failure_logs_its_event_name_with_a_traceback(
    monkeypatch: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """A teardown that itself fails must be reported, traceback attached.

    `record.exc_info` is checked for the (type, value, tb) triple rather than for
    non-None: logging stores exc_info=False verbatim, so a None check would pass
    with the flag turned off.
    """

    def _boom() -> None:
        raise RuntimeError("teardown exploded")

    monkeypatch.setattr(setup_mod, "shutdown_tracing", _boom)

    with caplog.at_level(logging.DEBUG, logger=setup_mod.__name__):
        setup_mod._rollback(["setup_tracing"])

    records = [r for r in caplog.records if r.name == setup_mod.__name__]
    assert [r.getMessage() for r in records] == ["setup.rollback.step_failed"]
    exc_info = records[0].exc_info
    assert isinstance(exc_info, tuple), f"exc_info=True must attach a triple, got {exc_info!r}"
    assert exc_info[0] is RuntimeError


def test_rollback_continues_past_a_failing_step(monkeypatch: Any) -> None:
    """Rollback is best-effort: a failing teardown must not skip the others."""
    called: list[str] = []

    def _boom() -> None:
        raise RuntimeError("teardown exploded")

    monkeypatch.setattr("provide.telemetry.metrics.provider.shutdown_metrics", _boom)
    monkeypatch.setattr(setup_mod, "shutdown_tracing", lambda: called.append("tracing"))

    setup_mod._rollback(["setup_tracing", "setup_metrics"])

    assert called == ["tracing"]


def test_degraded_setup_warning_blames_the_caller(monkeypatch: Any) -> None:
    """The warning must be a RuntimeWarning attributed one frame up.

    Captured off warnings.warn rather than the recorded frame: mutmut's
    trampoline adds a stack frame, so frame identity shifts under mutation.
    """
    calls: list[dict[str, Any]] = []

    def fake_warn(message: object, category: object = None, stacklevel: int = 1, **kw: Any) -> None:
        calls.append({"message": str(message), "category": category, "stacklevel": stacklevel})

    monkeypatch.setattr("provide.telemetry.setup.warnings.warn", fake_warn)

    def _boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("tracing refused to start")

    monkeypatch.setattr(setup_mod, "setup_tracing", _boom)

    setup_mod.setup_telemetry()

    degraded = [c for c in calls if "degraded mode" in c["message"]]
    assert len(degraded) == 1, f"expected one degraded-mode warning, got {calls!r}"
    assert degraded[0]["category"] is RuntimeWarning
    assert degraded[0]["stacklevel"] == 2
    assert "tracing refused to start" in degraded[0]["message"]


def _record_teardown_deadlines(monkeypatch: Any) -> list[float | None]:
    """Capture the deadline each per-signal teardown is handed."""
    seen: list[float | None] = []

    def _record(timeout_seconds: float | None = None) -> None:
        seen.append(timeout_seconds)

    monkeypatch.setattr(setup_mod, "shutdown_tracing", _record)
    monkeypatch.setattr(setup_mod, "shutdown_logging", _record)
    monkeypatch.setattr("provide.telemetry.metrics.provider.shutdown_metrics", _record)
    return seen


def test_shutdown_forwards_its_deadline_to_every_teardown(monkeypatch: Any) -> None:
    """The caller's timeout must bound every provider teardown.

    Each of the three runs force_flush + shutdown against its own endpoint under
    this deadline. Dropping it to None on any of them restores the configured
    default, which is exactly the overrun a SIGTERM handler passes a deadline to
    avoid.
    """
    seen = _record_teardown_deadlines(monkeypatch)

    setup_mod.shutdown_telemetry(timeout_seconds=1.5)

    assert seen == [1.5, 1.5, 1.5]


def test_shutdown_without_a_deadline_passes_none(monkeypatch: Any) -> None:
    seen = _record_teardown_deadlines(monkeypatch)

    setup_mod.shutdown_telemetry()

    assert seen == [None, None, None]
