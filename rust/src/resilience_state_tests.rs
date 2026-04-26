// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#![cfg(test)]

use super::*;

use crate::testing::acquire_test_state_lock;

async fn ok_unit_operation() -> Result<(), TelemetryError> {
    Ok(())
}

#[test]
fn resilience_test_missing_internal_state_surfaces_unknown_signal_errors() {
    let _guard = acquire_test_state_lock();
    _reset_resilience_for_tests();

    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime");
    assert_eq!(
        runtime
            .block_on(run_with_resilience(Signal::Logs, ok_unit_operation))
            .expect("healthy state should allow resilience wrapper"),
        Some(())
    );

    crate::_lock::lock(policies()).clear();
    let err = get_exporter_policy(Signal::Logs).expect_err("missing policy must error");
    assert!(err.message.contains("unknown signal"));

    let err = runtime
        .block_on(run_with_resilience(Signal::Logs, ok_unit_operation))
        .expect_err("missing policy must bubble up");
    assert!(err.message.contains("unknown signal"));

    crate::_lock::lock(circuits()).clear();
    let err = get_circuit_state(Signal::Logs).expect_err("missing circuit must error");
    assert!(err.message.contains("unknown signal"));

    _record_circuit_failure_for_wrappers(Signal::Logs, true);
    _record_circuit_success_for_wrappers(Signal::Logs);
    assert!(!_check_and_start_probe_for_wrappers(Signal::Logs));

    _reset_resilience_for_tests();
}

#[test]
fn resilience_test_record_success_closes_half_open_probe_state() {
    let _guard = acquire_test_state_lock();
    _reset_resilience_for_tests();

    {
        let mut lock = crate::_lock::lock(circuits());
        let state = lock
            .get_mut(&Signal::Logs)
            .expect("logs circuit must exist after reset");
        state.half_open_probing = true;
        state.consecutive_timeouts = 3;
    }

    _record_circuit_success_for_wrappers(Signal::Logs);

    let (state, _, _) = get_circuit_state(Signal::Logs).expect("logs circuit state should exist");
    assert_eq!(state, "closed");
    let lock = crate::_lock::lock(circuits());
    let state = lock
        .get(&Signal::Logs)
        .expect("logs circuit must exist after success");
    assert_eq!(state.consecutive_timeouts, 0);
    assert!(!state.half_open_probing);
}

#[test]
fn resilience_test_sleep_for_backoff_returns_without_tokio_reactor_flag() {
    let _guard = acquire_test_state_lock();
    assert!(backoff_duration(0.01, false).is_none());
}

#[test]
fn resilience_test_sleep_for_backoff_returns_for_zero_seconds() {
    let _guard = acquire_test_state_lock();
    assert!(backoff_duration(0.0, true).is_none());
}

#[test]
fn resilience_test_sleep_for_backoff_returns_some_when_positive_and_reactor_present() {
    let _guard = acquire_test_state_lock();
    assert_eq!(
        backoff_duration(0.5, true),
        Some(Duration::from_secs_f64(0.5))
    );
}

// Kills: `default_circuits_mutex` body replaced with `Mutex::new(BTreeMap::new())`.
// Every other test resets the circuit map before reading it, so the seeded
// entries are unobservable. This test calls the constructor directly and
// asserts all three signals are pre-populated.
#[test]
fn resilience_test_default_circuits_mutex_seeds_all_signals() {
    let mutex = default_circuits_mutex();
    let lock = mutex
        .lock()
        .expect("default_circuits_mutex should not be poisoned");
    assert_eq!(lock.len(), 3);
    assert!(lock.contains_key(&Signal::Logs));
    assert!(lock.contains_key(&Signal::Traces));
    assert!(lock.contains_key(&Signal::Metrics));
}

// Kills: `>=` -> `<` in _record_circuit_failure_for_wrappers's threshold check.
// Under `<`, the breaker would trip on every call below threshold (open_count
// would be 2 after three timeouts) instead of exactly once at the threshold.
#[test]
fn resilience_test_record_failure_trips_breaker_exactly_at_threshold() {
    let _guard = acquire_test_state_lock();
    _reset_resilience_for_tests();

    for _ in 0..CIRCUIT_BREAKER_THRESHOLD {
        _record_circuit_failure_for_wrappers(Signal::Logs, true);
    }

    let lock = crate::_lock::lock(circuits());
    let state = lock
        .get(&Signal::Logs)
        .expect("logs circuit must exist after reset");
    assert_eq!(state.consecutive_timeouts, CIRCUIT_BREAKER_THRESHOLD);
    assert_eq!(
        state.open_count, 1,
        "breaker must trip exactly once at the threshold"
    );
    assert!(state.tripped_at.is_some());
}

#[test]
fn resilience_test_cooldown_remaining_is_zero_without_trip_timestamp() {
    let _guard = acquire_test_state_lock();

    assert_eq!(cooldown_remaining(None), 0.0);
}
