// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// Mutation tests for health.rs

use provide_telemetry::get_health_snapshot;

#[test]
fn test_health_snapshot_creation() {
    // Verify that get_health_snapshot() returns a value without panicking.
    let snapshot = get_health_snapshot();
    let _ = snapshot.emitted_logs;
    let _ = snapshot.dropped_logs;
}

#[test]
fn test_health_snapshot_initialization() {
    let snapshot = get_health_snapshot();
    assert_eq!(snapshot.emitted_logs, 0);
    assert_eq!(snapshot.dropped_logs, 0);
    assert_eq!(snapshot.emitted_traces, 0);
}

#[test]
fn test_health_snapshot_all_non_negative() {
    // All counter fields start at 0 on a fresh snapshot (u64, always non-negative).
    let snapshot = get_health_snapshot();
    assert_eq!(snapshot.emitted_logs, 0);
    assert_eq!(snapshot.dropped_logs, 0);
    assert_eq!(snapshot.emitted_traces, 0);
    assert_eq!(snapshot.dropped_traces, 0);
    assert_eq!(snapshot.emitted_metrics, 0);
    assert_eq!(snapshot.dropped_metrics, 0);
}

#[test]
fn test_health_snapshot_latencies() {
    // Latency fields start at 0.0 (no exports recorded yet).
    let snapshot = get_health_snapshot();
    assert_eq!(snapshot.export_latency_ms_logs, 0.0);
    assert_eq!(snapshot.export_latency_ms_traces, 0.0);
    assert_eq!(snapshot.export_latency_ms_metrics, 0.0);
}
