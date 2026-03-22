# Executor Saturation Load Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `tests/resilience/test_executor_saturation.py` covering ghost thread accumulation, circuit breaker lifecycle, and cross-signal isolation under sustained export failures.

**Architecture:** Three test classes using event-gated fake operations (no `time.sleep`) to control exactly when stuck threads unblock. `time.monotonic` is replaced on the resilience module namespace (not the global `time` module) to advance the synthetic clock past the 30 s circuit-breaker cooldown without waiting.

**Tech Stack:** pytest, `threading.Event`, `types.SimpleNamespace`, `resilience_mod` private state inspection (`_consecutive_timeouts`, `_circuit_tripped_at`), `threading.active_count()`

---

## File Map

| Action | Path |
|--------|------|
| Create | `tests/resilience/test_executor_saturation.py` |

No source changes required — this is a pure test addition.

---

### Task 1: Scaffold the file with fixtures and helpers

**Files:**
- Create: `tests/resilience/test_executor_saturation.py`

- [ ] **Step 1: Create the file with SPDX header, imports, fixtures, and helper**

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Executor saturation load tests for resilience.py.

Tests three failure modes under sustained export failures:
- Ghost thread accumulation: circuit breaker bounds thread growth.
- Circuit breaker lifecycle: trip → block → half-open → reset → re-trip.
- Cross-signal isolation: a logs timeout storm cannot starve traces/metrics workers.
"""

from __future__ import annotations

import threading
import time
import types
from collections.abc import Callable, Iterator
import pytest

from undef.telemetry import health as health_mod
from undef.telemetry import resilience as resilience_mod
from undef.telemetry.resilience import ExporterPolicy, run_with_resilience

pytestmark = pytest.mark.integration

_TIMEOUT_S = 0.005  # 5 ms — tight enough to reliably time out a blocked op


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    resilience_mod.reset_resilience_for_tests()
    health_mod.reset_health_for_tests()
    yield
    # Tests must release their own events before this runs.
    # reset_resilience_for_tests() shuts down executors (wait=False) and clears
    # _timeout_executors so the next test gets a fresh pool.
    resilience_mod.reset_resilience_for_tests()
    health_mod.reset_health_for_tests()


def _make_stuck_op(event: threading.Event) -> Callable[[], str]:
    """Return an operation that blocks until *event* is set (5 s safety cap)."""

    def _op() -> str:
        event.wait(timeout=5.0)
        return "done"

    return _op


def _tight_policy(signal: str) -> None:
    """Set a tight-timeout, no-retry, fail-open policy for *signal*."""
    resilience_mod.set_exporter_policy(
        signal,
        ExporterPolicy(retries=0, timeout_seconds=_TIMEOUT_S, fail_open=True),
    )


def _trip_circuit(signal: str, event: threading.Event) -> None:
    """Submit exactly _CIRCUIT_BREAKER_THRESHOLD slow ops to trip the circuit."""
    threshold = resilience_mod._CIRCUIT_BREAKER_THRESHOLD
    for _ in range(threshold):
        result = run_with_resilience(signal, _make_stuck_op(event))
        assert result is None  # fail_open returns None on timeout
```

- [ ] **Step 2: Verify file parses cleanly**

```bash
uv run python -c "import tests.resilience.test_executor_saturation"
```

Expected: no output (clean import).

- [ ] **Step 3: Commit scaffold**

```bash
git add tests/resilience/test_executor_saturation.py
git commit -m "test: scaffold executor saturation test file with fixtures and helpers"
```

---

### Task 2: TestGhostThreadAccumulation

**Files:**
- Modify: `tests/resilience/test_executor_saturation.py`

Ghost threads are daemon threads that remain alive after a future times out (because
`future.cancel()` only prevents queued tasks; already-running tasks keep going).  The
circuit breaker should trip after `_CIRCUIT_BREAKER_THRESHOLD` timeouts and stop
submitting new work, bounding thread growth to the executor's `max_workers` (2).

- [ ] **Step 1: Write the test — run it to see FAIL (NameError or collection error)**

Add this class to `test_executor_saturation.py`:

```python
class TestGhostThreadAccumulation:
    def test_circuit_breaker_bounds_ghost_threads(self) -> None:
        """Circuit breaker trips after threshold timeouts; no further threads accumulate."""
        event = threading.Event()  # held closed — ops will block and time out
        _tight_policy("logs")
        baseline = threading.active_count()

        # Trip the circuit (threshold = 3 consecutive timeouts)
        _trip_circuit("logs", event)

        # After tripping: at most 2 ghost threads (the 2 executor workers).
        # Further calls are rejected by the open circuit without submitting.
        assert threading.active_count() <= baseline + 2

        call_count = 0

        def _counting_op() -> str:
            nonlocal call_count
            call_count += 1
            return "should not run"

        # With circuit open, these must be rejected without calling the operation.
        for _ in range(5):
            result = run_with_resilience("logs", _counting_op)
            assert result is None

        assert call_count == 0  # operation never called
        assert threading.active_count() <= baseline + 2  # no new threads

        # Drain: release event so stuck threads can finish, then shut down executor.
        event.set()
        resilience_mod.reset_resilience_for_tests()
        health_mod.reset_health_for_tests()

        # executor.shutdown(wait=False) returns immediately; worker threads need a
        # moment to finish their event.wait() call and exit.  Poll rather than
        # assert immediately to avoid a race on loaded CI machines.
        deadline = time.monotonic() + 2.0
        while threading.active_count() > baseline and time.monotonic() < deadline:
            time.sleep(0.005)
        assert threading.active_count() == baseline
```

- [ ] **Step 2: Run test to confirm it passes**

```bash
uv run python scripts/run_pytest_gate.py --no-cov -q -k "test_circuit_breaker_bounds_ghost_threads"
```

Expected: `1 passed`

- [ ] **Step 3: Commit**

```bash
git add tests/resilience/test_executor_saturation.py
git commit -m "test: add ghost thread accumulation test"
```

---

### Task 3: TestCircuitBreakerLifecycle

**Files:**
- Modify: `tests/resilience/test_executor_saturation.py`

This test covers the full state machine:
- `CLOSED` → trip after 3 timeouts → `OPEN`
- `OPEN` → block traffic (no calls) → cooldown expires → `HALF-OPEN` probe
- Successful probe → `CLOSED` (counter reset)
- Re-trip → `OPEN` again
- Failed half-open probe → immediate `OPEN`

`time.monotonic` is replaced on the resilience module namespace via
`monkeypatch.setattr(resilience_mod, "time", fake_time)` so we skip the real 30 s wait.
The fake time object must provide `.monotonic()`, `.perf_counter()`, and `.sleep()`.

- [ ] **Step 1: Write the test**

```python
class TestCircuitBreakerLifecycle:
    def test_full_lifecycle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Trip → block → half-open success → reset → re-trip → half-open failure."""
        event = threading.Event()
        _tight_policy("logs")

        # ── 1. Trip ──────────────────────────────────────────────────────────
        _trip_circuit("logs", event)
        assert resilience_mod._consecutive_timeouts["logs"] == resilience_mod._CIRCUIT_BREAKER_THRESHOLD

        # ── 2. Block ─────────────────────────────────────────────────────────
        not_called: list[bool] = []

        def _sentinel() -> str:
            not_called.append(True)
            return "oops"

        result = run_with_resilience("logs", _sentinel)
        assert result is None  # circuit open → fail_open → None
        assert not_called == []  # sentinel never ran
        snap = health_mod.get_health_snapshot()
        # Failures = 3 timeouts + 1 circuit-open rejection
        assert snap.export_failures_logs == resilience_mod._CIRCUIT_BREAKER_THRESHOLD + 1

        # ── 3. Advance clock past cooldown ───────────────────────────────────
        tripped_at = resilience_mod._circuit_tripped_at["logs"]
        fake_time = types.SimpleNamespace(
            monotonic=lambda: tripped_at + resilience_mod._CIRCUIT_BREAKER_COOLDOWN + 1.0,
            perf_counter=time.perf_counter,
            sleep=time.sleep,
        )
        monkeypatch.setattr(resilience_mod, "time", fake_time)

        # ── 4. Half-open probe — success ─────────────────────────────────────
        # Release the stuck event so the probe completes within timeout.
        event.set()
        probe_result = run_with_resilience("logs", lambda: "probe-ok")
        assert probe_result == "probe-ok"
        assert resilience_mod._consecutive_timeouts["logs"] == 0  # reset on success

        # ── 5. Re-trip ───────────────────────────────────────────────────────
        # future.result(timeout=...) raises TimeoutError whether the task is
        # queued or running, so this is correct even if the executor workers are
        # still occupied by the previous batch's draining threads.
        event.clear()
        # Restore real time so timeouts fire normally.
        monkeypatch.setattr(resilience_mod, "time", time)
        _trip_circuit("logs", event)
        assert resilience_mod._consecutive_timeouts["logs"] == resilience_mod._CIRCUIT_BREAKER_THRESHOLD

        # ── 6. Half-open probe — failure ─────────────────────────────────────
        tripped_at2 = resilience_mod._circuit_tripped_at["logs"]
        fake_time2 = types.SimpleNamespace(
            monotonic=lambda: tripped_at2 + resilience_mod._CIRCUIT_BREAKER_COOLDOWN + 1.0,
            perf_counter=time.perf_counter,
            sleep=time.sleep,
        )
        monkeypatch.setattr(resilience_mod, "time", fake_time2)

        # Probe times out (event still closed) → circuit re-trips.
        result2 = run_with_resilience("logs", _make_stuck_op(event))
        assert result2 is None
        assert (
            resilience_mod._consecutive_timeouts["logs"]
            >= resilience_mod._CIRCUIT_BREAKER_THRESHOLD
        )

        # Cleanup
        event.set()
```

- [ ] **Step 2: Run to confirm it passes**

```bash
uv run python scripts/run_pytest_gate.py --no-cov -q -k "test_full_lifecycle"
```

Expected: `1 passed`

- [ ] **Step 3: Commit**

```bash
git add tests/resilience/test_executor_saturation.py
git commit -m "test: add circuit breaker lifecycle test"
```

---

### Task 4: TestCrossSignalIsolation

**Files:**
- Modify: `tests/resilience/test_executor_saturation.py`

Each signal has its own 2-worker `ThreadPoolExecutor`.  A timeout storm on "logs"
occupies only the "logs" executor's workers; "traces" and "metrics" have independent
pools and must remain fully operational.

- [ ] **Step 1: Write the test**

```python
class TestCrossSignalIsolation:
    def test_logs_storm_does_not_starve_traces_or_metrics(self) -> None:
        """A timeout storm on logs leaves traces and metrics unaffected."""
        logs_event = threading.Event()  # held closed — logs ops will time out
        _tight_policy("logs")
        # Use a generous timeout for traces/metrics so they succeed comfortably.
        resilience_mod.set_exporter_policy(
            "traces",
            ExporterPolicy(retries=0, timeout_seconds=1.0, fail_open=True),
        )
        resilience_mod.set_exporter_policy(
            "metrics",
            ExporterPolicy(retries=0, timeout_seconds=1.0, fail_open=True),
        )

        # Trip the logs circuit — 2 workers now hold stuck threads.
        _trip_circuit("logs", logs_event)

        # While logs workers are occupied, traces and metrics must still work.
        traces_result = run_with_resilience("traces", lambda: "traces-ok")
        metrics_result = run_with_resilience("metrics", lambda: "metrics-ok")

        assert traces_result == "traces-ok"
        assert metrics_result == "metrics-ok"

        # Health counters: only logs has failures.
        snap = health_mod.get_health_snapshot()
        assert snap.export_failures_traces == 0
        assert snap.export_failures_metrics == 0
        assert snap.export_failures_logs == resilience_mod._CIRCUIT_BREAKER_THRESHOLD

        # Timeout counters: only logs is non-zero.
        assert resilience_mod._consecutive_timeouts["traces"] == 0
        assert resilience_mod._consecutive_timeouts["metrics"] == 0

        # Cleanup
        logs_event.set()
```

- [ ] **Step 2: Run to confirm it passes**

```bash
uv run python scripts/run_pytest_gate.py --no-cov -q -k "test_logs_storm_does_not_starve"
```

Expected: `1 passed`

- [ ] **Step 3: Commit**

```bash
git add tests/resilience/test_executor_saturation.py
git commit -m "test: add cross-signal isolation test"
```

---

### Task 5: Full quality gate

**Files:** none (verification only)

- [ ] **Step 1: Run the full coverage gate**

```bash
uv run python scripts/run_pytest_gate.py
```

Expected: `100%` coverage, all tests pass.  If any branch is uncovered, add a targeted
test or adjust the existing ones to reach the missed branch.

- [ ] **Step 2: Lint and type-check**

```bash
uv run ruff check . && uv run mypy src tests
```

Expected: no errors.

- [ ] **Step 3: LOC and SPDX checks**

```bash
uv run python scripts/check_max_loc.py --max-lines 500
uv run python scripts/check_spdx_headers.py
```

Expected: both pass.  If `test_executor_saturation.py` is over 500 lines, split
`TestCircuitBreakerLifecycle` into a second file `test_circuit_breaker_lifecycle.py`.

- [ ] **Step 4: Final commit if any fixes were needed**

```bash
git add -p   # stage only the affected files
git commit -m "test: fix coverage gaps in executor saturation tests"
```
