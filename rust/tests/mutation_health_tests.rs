// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// Mutation tests for health.rs

use provide_telemetry::get_health_snapshot;

#[test]
fn test_health_snapshot_creation() {
    let snapshot = get_health_snapshot();
    assert!(snapshot.emitted_logs >= 0);
    assert!(snapshot.dropped_logs >= 0);
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
    let snapshot = get_health_snapshot();
    assert!(snapshot.emitted_logs >= 0);
    assert!(snapshot.dropped_logs >= 0);
    assert!(snapshot.emitted_traces >= 0);
    assert!(snapshot.dropped_traces >= 0);
    assert!(snapshot.emitted_metrics >= 0);
    assert!(snapshot.dropped_metrics >= 0);
}

#[test]
fn test_health_snapshot_latencies() {
    let snapshot = get_health_snapshot();
    assert!(snapshot.export_latency_ms_logs >= 0.0);
    assert!(snapshot.export_latency_ms_traces >= 0.0);
    assert!(snapshot.export_latency_ms_metrics >= 0.0);
}
