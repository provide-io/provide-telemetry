// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use std::sync::{Mutex, OnceLock};

use provide_telemetry::{get_health_snapshot, Signal};

static HEALTH_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn health_lock() -> &'static Mutex<()> {
    HEALTH_LOCK.get_or_init(|| Mutex::new(()))
}

fn reset() {
    provide_telemetry::health::_reset_health_for_tests();
}

#[test]
fn test_health_snapshot_creation() {
    let _guard = health_lock().lock().expect("health lock poisoned");
    reset();
    let snapshot = get_health_snapshot();
    let _ = snapshot.emitted_logs;
    let _ = snapshot.dropped_logs;
}

#[test]
fn test_health_snapshot_initialization() {
    let _guard = health_lock().lock().expect("health lock poisoned");
    reset();
    let snapshot = get_health_snapshot();
    assert_eq!(snapshot.emitted_logs, 0);
    assert_eq!(snapshot.dropped_logs, 0);
    assert_eq!(snapshot.emitted_traces, 0);
}

#[test]
fn test_health_snapshot_all_non_negative() {
    let _guard = health_lock().lock().expect("health lock poisoned");
    reset();
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
    let _guard = health_lock().lock().expect("health lock poisoned");
    reset();
    let snapshot = get_health_snapshot();
    assert_eq!(snapshot.export_latency_ms_logs, 0.0);
    assert_eq!(snapshot.export_latency_ms_traces, 0.0);
    assert_eq!(snapshot.export_latency_ms_metrics, 0.0);
}

#[test]
fn health_test_increment_dropped_all_signals() {
    let _guard = health_lock().lock().expect("health lock poisoned");
    reset();
    provide_telemetry::health::increment_dropped(Signal::Logs, 3);
    provide_telemetry::health::increment_dropped(Signal::Traces, 5);
    provide_telemetry::health::increment_dropped(Signal::Metrics, 7);
    let snap = get_health_snapshot();
    assert_eq!(snap.dropped_logs, 3);
    assert_eq!(snap.dropped_traces, 5);
    assert_eq!(snap.dropped_metrics, 7);
}

#[test]
fn health_test_increment_retries_all_signals() {
    let _guard = health_lock().lock().expect("health lock poisoned");
    reset();
    provide_telemetry::health::increment_retries(Signal::Logs, 2);
    provide_telemetry::health::increment_retries(Signal::Traces, 4);
    provide_telemetry::health::increment_retries(Signal::Metrics, 6);
    let snap = get_health_snapshot();
    assert_eq!(snap.retries_logs, 2);
    assert_eq!(snap.retries_traces, 4);
    assert_eq!(snap.retries_metrics, 6);
}

#[test]
fn health_test_record_export_failure_all_signals() {
    let _guard = health_lock().lock().expect("health lock poisoned");
    reset();
    provide_telemetry::health::record_export_failure(Signal::Logs);
    provide_telemetry::health::record_export_failure(Signal::Traces);
    provide_telemetry::health::record_export_failure(Signal::Metrics);
    let snap = get_health_snapshot();
    assert_eq!(snap.export_failures_logs, 1);
    assert_eq!(snap.export_failures_traces, 1);
    assert_eq!(snap.export_failures_metrics, 1);
}

#[test]
fn health_test_record_export_latency_all_signals() {
    let _guard = health_lock().lock().expect("health lock poisoned");
    reset();
    provide_telemetry::health::record_export_latency(Signal::Logs, 12.5);
    provide_telemetry::health::record_export_latency(Signal::Traces, 34.0);
    provide_telemetry::health::record_export_latency(Signal::Metrics, 56.75);
    let snap = get_health_snapshot();
    assert!((snap.export_latency_ms_logs - 12.5).abs() < 1e-9);
    assert!((snap.export_latency_ms_traces - 34.0).abs() < 1e-9);
    assert!((snap.export_latency_ms_metrics - 56.75).abs() < 1e-9);
}
