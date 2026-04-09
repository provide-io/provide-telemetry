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
