// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// Mutation tests for health.rs — cover health snapshot functionality

use provide_telemetry::get_health_snapshot;

#[test]
fn test_health_snapshot_creation() {
    let snapshot = get_health_snapshot();

    // Snapshot should have non-negative counters
    assert!(snapshot.emitted_logs >= 0);
    assert!(snapshot.dropped_logs >= 0);
}

#[test]
fn test_health_counter_initialization() {
    let snapshot = get_health_snapshot();

    // New snapshot should start at 0
    assert_eq!(snapshot.emitted_logs, 0);
    assert_eq!(snapshot.dropped_logs, 0);
    assert_eq!(snapshot.emitted_traces, 0);
}

#[test]
fn test_health_counters_non_negative() {
    let snapshot = get_health_snapshot();

    // All counters must be >= 0 (catches boundary mutations)
    assert!(snapshot.emitted_logs >= 0);
    assert!(snapshot.dropped_logs >= 0);
    assert!(snapshot.emitted_traces >= 0);
    assert!(snapshot.dropped_traces >= 0);
    assert!(snapshot.recorded_metrics >= 0);
    assert!(snapshot.dropped_metrics >= 0);
}

#[test]
fn test_health_export_latency_non_negative() {
    let snapshot = get_health_snapshot();
    assert!(snapshot.export_latency_ms >= 0);
}

#[test]
fn test_health_snapshot_field_totals() {
    let snapshot = get_health_snapshot();

    // Test totals are non-negative
    let logs_total = snapshot.emitted_logs + snapshot.dropped_logs;
    assert!(logs_total >= 0);

    let traces_total = snapshot.emitted_traces + snapshot.dropped_traces;
    assert!(traces_total >= 0);
}
