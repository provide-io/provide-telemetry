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

    policies().lock().expect("policy lock poisoned").clear();
    let err = get_exporter_policy(Signal::Logs).expect_err("missing policy must error");
    assert!(err.message.contains("unknown signal"));

    let err = runtime
        .block_on(run_with_resilience(Signal::Logs, ok_unit_operation))
        .expect_err("missing policy must bubble up");
    assert!(err.message.contains("unknown signal"));

    circuits().lock().expect("circuit lock poisoned").clear();
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
        let mut lock = circuits().lock().expect("circuit lock poisoned");
        let state = lock
            .get_mut(&Signal::Logs)
            .expect("logs circuit must exist after reset");
        state.half_open_probing = true;
        state.consecutive_timeouts = 3;
    }

    _record_circuit_success_for_wrappers(Signal::Logs);

    let (state, _, _) = get_circuit_state(Signal::Logs).expect("logs circuit state should exist");
    assert_eq!(state, "closed");
    let lock = circuits().lock().expect("circuit lock poisoned");
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
fn resilience_test_cooldown_remaining_is_zero_without_trip_timestamp() {
    let _guard = acquire_test_state_lock();

    assert_eq!(cooldown_remaining(None), 0.0);
}
