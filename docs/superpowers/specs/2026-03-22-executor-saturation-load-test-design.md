# Executor Saturation Load Test — Design Spec

**Date:** 2026-03-22
**File:** `tests/resilience/test_executor_saturation.py`
**Suite:** default coverage gate (100% required)

---

## Problem

`resilience.py` uses per-signal `ThreadPoolExecutor(max_workers=2)` instances to run
export operations with a timeout.  When an operation times out, `future.cancel()` is
called — but that only prevents *queued* tasks; an already-running operation continues
on a daemon thread.  Under sustained export failures three failure modes are untested:

1. **Ghost thread accumulation** — timed-out operations pile up as live daemon threads
   because `cancel()` doesn't kill them.  Without the circuit breaker, the 2-worker pool
   stays permanently occupied and new futures queue indefinitely.
2. **Circuit breaker lifecycle** — the breaker trips after 3 consecutive timeouts, blocks
   traffic during the 30 s cooldown, then allows one half-open probe.  A successful probe
   resets the counter; a failing probe re-trips immediately.  This full lifecycle is untested
   under real contention.
3. **Cross-signal isolation** — each signal has its own 2-worker pool specifically to
   prevent a timeout storm on one signal from starving the others.  This property has never
   been tested with real stuck threads.

---

## Design

### Approach: event-gated operations + monkeypatched `time.monotonic`

- **Event-gated operations** — the fake export op blocks on a `threading.Event.wait()`
  we control.  The executor timeout fires deterministically (tight timeout, e.g. 5 ms).
  After the test's assertions, we release all held events so ghost threads drain.
  No wall-clock sleeps needed; `threading.active_count()` gives an accurate thread count.
- **Monkeypatched `time.monotonic`** — the circuit-breaker cooldown is 30 s.  We
  monkeypatch `resilience_mod.time` to return a synthetic clock that we advance manually,
  skipping the real wait.

### Test file: `tests/resilience/test_executor_saturation.py`

Three test classes, all under `pytestmark = pytest.mark.integration`:

#### `TestGhostThreadAccumulation`

Goal: verify the circuit breaker bounds ghost thread growth.

1. Record baseline `threading.active_count()`.
2. Set a tight timeout policy (5 ms, no retries, `fail_open=True`).
3. Submit enough calls to trip the circuit breaker (3 timeouts) while the fake op
   blocks on an event.
4. Submit further calls — assert they are rejected by the open circuit (operation
   not called, `fail_open` returns `None`).
5. Assert `threading.active_count()` has not grown beyond baseline + 2 (the 2 executor
   workers per signal; further submissions are queued but only 2 threads run).
6. Release all events so ghost threads can finish.
7. Call `reset_resilience_for_tests()` to shut down the executor (drains workers).
   Assert `threading.active_count()` returns to baseline (executor threads are gone).

#### `TestCircuitBreakerLifecycle`

Goal: verify the full trip → block → half-open → reset and trip → block → re-trip
sequences under a controlled clock.

1. **Trip:** submit 3 slow ops (events held), assert circuit trips after 3rd timeout.
2. **Block:** submit a 4th op, assert it is rejected without calling the operation.
   Assert health counters show the rejection.
3. **Cooldown advance:** monkeypatch `resilience_mod.time.monotonic` to return
   `_circuit_tripped_at[sig] + 31.0` (past cooldown).
4. **Half-open probe — success:** set the event *before* submitting the probe call
   so the operation completes within timeout.  Assert `run_with_resilience` returns
   the expected value, and `resilience_mod._consecutive_timeouts["logs"] == 0` (reset
   on success).
5. **Re-trip:** use a fresh event (held closed), release events from step 3 first so
   executor workers are free, then submit 3 more slow ops; assert circuit re-trips.
6. **Half-open probe — failure:** advance clock past cooldown again; submit a slow op;
   assert circuit re-trips immediately on the probe timeout.

#### `TestCrossSignalIsolation`

Goal: verify that a timeout storm on "logs" does not block "traces" or "metrics" workers.

1. Hold the event open; trip "logs" circuit (3 timeouts).
2. While "logs" workers may still hold stuck threads, submit successful ops on "traces"
   and "metrics" (events released immediately) and assert they complete with the correct
   return value.
3. Assert "traces" and "metrics" health counters show zero failures.
4. Assert `_consecutive_timeouts["traces"] == 0` and same for "metrics".
5. Release all "logs" events.

---

## Fixtures and helpers

```python
@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    resilience_mod.reset_resilience_for_tests()
    health_mod.reset_health_for_tests()
    yield
    # Each test is responsible for releasing its own events before yielding
    # back; the executor shutdown here is non-blocking so ghost threads may
    # still be running — that's fine because reset_resilience_for_tests()
    # replaces the executor dict, isolating state for the next test.
    resilience_mod.reset_resilience_for_tests()
    health_mod.reset_health_for_tests()
```

```python
def _make_stuck_op(event: threading.Event) -> Callable[[], str]:
    """Returns an operation that blocks until `event` is set."""
    def _op() -> str:
        event.wait(timeout=5.0)  # 5s safety timeout so tests can't hang
        return "done"
    return _op
```

### Monkeypatching `time.monotonic`

`resilience.py` does `import time` and calls `time.monotonic()`, `time.perf_counter()`,
and `time.sleep()`.  To advance the synthetic clock safely (without affecting other
modules) replace the name binding at the module level:

```python
import types

fake_time = types.SimpleNamespace(
    monotonic=lambda: synthetic_value,
    perf_counter=time.perf_counter,   # real perf_counter is fine
    sleep=time.sleep,                 # real sleep is fine (tests avoid sleeping)
)
monkeypatch.setattr(resilience_mod, "time", fake_time)
```

Do **not** patch `resilience_mod.time.monotonic` directly — that mutates the global
`time` module object and affects all other modules in the process.

---

## Constraints

- File must stay under 500 LOC.
- All new code paths must be reachable (100% branch coverage).
- Marker: `pytest.mark.integration` (already included in default gate run).
- No `time.sleep()` in tests (use event synchronisation instead).
- Release all held events in teardown to prevent thread leaks across tests.
