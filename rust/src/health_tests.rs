use super::*;

use crate::resilience::{_clear_resilience_state_for_tests, _reset_resilience_for_tests};
use crate::testing::acquire_test_state_lock;

#[test]
fn health_test_increment_and_latency_roundtrip() {
    let _guard = acquire_test_state_lock();
    _reset_health_for_tests();

    crate::health::increment_dropped(Signal::Logs, 3);
    crate::health::increment_emitted(Signal::Traces, 5);
    crate::health::increment_retries(Signal::Metrics, 7);
    crate::health::record_export_failure(Signal::Logs);
    crate::health::record_export_latency(Signal::Traces, 12.5);

    let snapshot = get_health_snapshot();
    assert_eq!(snapshot.dropped_logs, 3);
    assert_eq!(snapshot.emitted_traces, 5);
    assert_eq!(snapshot.retries_metrics, 7);
    assert_eq!(snapshot.export_failures_logs, 1);
    assert!((snapshot.export_latency_ms_traces - 12.5).abs() < 1e-9);
}

/// Without this counter a sink that quietly refuses every receipt looks exactly
/// like one that delivers them, so the failure has to be visible somewhere the
/// receipt path itself can reach — and it cannot log.
#[test]
fn health_test_receipt_failures_are_counted() {
    let _guard = acquire_test_state_lock();
    _reset_health_for_tests();

    assert_eq!(get_health_snapshot().receipt_failures, 0);
    crate::health::increment_receipt_failures();
    crate::health::increment_receipt_failures();

    assert_eq!(get_health_snapshot().receipt_failures, 2);
}

#[test]
fn health_test_snapshot_reads_all_three_circuit_states() {
    let _guard = acquire_test_state_lock();
    _reset_health_for_tests();
    _reset_resilience_for_tests();

    let snapshot = get_health_snapshot();

    assert_eq!(snapshot.circuit_state_logs, "closed");
    assert_eq!(snapshot.circuit_state_traces, "closed");
    assert_eq!(snapshot.circuit_state_metrics, "closed");
    assert_eq!(snapshot.circuit_open_count_logs, 0);
    assert_eq!(snapshot.circuit_open_count_traces, 0);
    assert_eq!(snapshot.circuit_open_count_metrics, 0);
}

#[test]
fn health_test_snapshot_ignores_missing_circuit_states() {
    let _guard = acquire_test_state_lock();
    _reset_health_for_tests();
    _reset_resilience_for_tests();
    _clear_resilience_state_for_tests();

    let snapshot = get_health_snapshot();

    assert_eq!(snapshot.circuit_state_logs, "");
    assert_eq!(snapshot.circuit_state_traces, "");
    assert_eq!(snapshot.circuit_state_metrics, "");
}

/// Each signal's counter must actually add — a stuck-at-zero counter reports
/// "no executor ever stalled" forever, which is the one lie this counter
/// exists to prevent.
#[test]
fn health_test_async_blocking_risk_increments_per_signal() {
    let _guard = acquire_test_state_lock();
    _reset_health_for_tests();

    crate::health::increment_async_blocking_risk(Signal::Logs);
    crate::health::increment_async_blocking_risk(Signal::Traces);
    crate::health::increment_async_blocking_risk(Signal::Traces);
    crate::health::increment_async_blocking_risk(Signal::Metrics);
    crate::health::increment_async_blocking_risk(Signal::Metrics);
    crate::health::increment_async_blocking_risk(Signal::Metrics);

    let snapshot = get_health_snapshot();
    assert_eq!(snapshot.async_blocking_risk_logs, 1);
    assert_eq!(snapshot.async_blocking_risk_traces, 2);
    assert_eq!(snapshot.async_blocking_risk_metrics, 3);
}
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
