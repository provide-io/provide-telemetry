# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Regression tests for code review batch #10 (shared test-state hygiene)."""

from __future__ import annotations

import inspect
import time

from provide.telemetry import resilience as resilience_mod


def test_root_conftest_reset_clears_resilience_state() -> None:
    """The shared test reset must close any previously tripped circuit breaker."""
    import tests.conftest as root_conftest

    resilience_mod._consecutive_timeouts["logs"] = resilience_mod._CIRCUIT_BREAKER_THRESHOLD
    resilience_mod._circuit_tripped_at["logs"] = time.monotonic()
    resilience_mod._open_count["logs"] = 2
    resilience_mod._half_open_probing["logs"] = True

    inspect.unwrap(root_conftest.reset_logger_state)()

    assert resilience_mod.get_circuit_state("logs") == ("closed", 0, 0.0)
