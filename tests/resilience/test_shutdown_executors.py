# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for shutdown_timeout_executors and integration with shutdown_telemetry."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from provide.telemetry.resilience import (
    _get_timeout_executor,
    _timeout_executors,
    reset_resilience_for_tests,
    run_with_resilience,
    shutdown_timeout_executors,
)
from provide.telemetry.setup import _reset_all_for_tests, setup_telemetry, shutdown_telemetry


@pytest.fixture(autouse=True)
def _reset() -> Generator[None, None, None]:
    reset_resilience_for_tests()
    yield
    reset_resilience_for_tests()


def test_shutdown_timeout_executors_clears_dict() -> None:
    _get_timeout_executor("logs")
    assert "logs" in _timeout_executors
    shutdown_timeout_executors()
    assert _timeout_executors == {}


def test_shutdown_timeout_executors_is_idempotent() -> None:
    _get_timeout_executor("traces")
    shutdown_timeout_executors()
    shutdown_timeout_executors()  # must not raise
    assert _timeout_executors == {}


def test_shutdown_timeout_executors_empty_is_safe() -> None:
    assert _timeout_executors == {}
    shutdown_timeout_executors()  # no executors created — must not raise
    assert _timeout_executors == {}


def test_shutdown_timeout_executors_clears_all_signals() -> None:
    for sig in ("logs", "traces", "metrics"):
        _get_timeout_executor(sig)
    assert len(_timeout_executors) == 3
    shutdown_timeout_executors()
    assert _timeout_executors == {}


def test_shutdown_telemetry_clears_executors() -> None:
    _reset_all_for_tests()
    setup_telemetry()
    # Force executor creation by running an operation with timeout
    run_with_resilience("logs", lambda: None)
    assert "logs" in _timeout_executors
    shutdown_telemetry()
    assert _timeout_executors == {}
    _reset_all_for_tests()


# ── Mutation kill: shutdown(wait=False) vs wait=True ────────────────────────


def test_shutdown_timeout_executors_calls_shutdown_with_wait_false() -> None:
    """Kill mutant: executor.shutdown(wait=False) → wait=True.

    Verifies that the ``wait`` keyword is exactly False so the call is
    non-blocking (daemon threads are abandoned rather than joined).
    """
    for sig in ("logs", "traces", "metrics"):
        _get_timeout_executor(sig)

    from unittest.mock import patch

    shutdown_calls: list[tuple[object, ...]] = []

    original_shutdown = None

    def _recording_shutdown(wait: bool) -> None:
        shutdown_calls.append((wait,))
        if original_shutdown is not None:
            original_shutdown(wait=wait)

    # Patch each executor's shutdown method to record the call
    executors = list(_timeout_executors.values())
    patches = []
    for ex in executors:
        p = patch.object(ex, "shutdown", side_effect=_recording_shutdown)
        patches.append(p)

    for p in patches:
        p.start()

    try:
        shutdown_timeout_executors()
    finally:
        for p in patches:
            p.stop()

    assert len(shutdown_calls) == 3, "Expected one shutdown() call per executor"
    for args in shutdown_calls:
        assert args == (False,), f"Expected wait=False, got wait={args[0]}"


def test_shutdown_timeout_executors_clear_removes_all_entries() -> None:
    """Kill mutant: _timeout_executors.clear() removed or no-op.

    After shutdown, the dict must be empty so subsequent calls see no executors.
    """
    for sig in ("logs", "traces", "metrics"):
        _get_timeout_executor(sig)

    assert len(_timeout_executors) == 3
    shutdown_timeout_executors()
    assert len(_timeout_executors) == 0, "_timeout_executors must be empty after shutdown"
