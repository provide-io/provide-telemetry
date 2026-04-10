// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// Mutation tests for resilience.rs

use provide_telemetry::{get_exporter_policy, set_exporter_policy, ExporterPolicy, Signal};

#[test]
fn test_exporter_policy_default() {
    let policy = get_exporter_policy(Signal::Logs).expect("logs policy exists");
    let _ = policy;
}

#[test]
fn test_set_exporter_policy() {
    let policy = ExporterPolicy::default();
    set_exporter_policy(Signal::Logs, policy).expect("set ok");
    let retrieved = get_exporter_policy(Signal::Logs).expect("get ok");
    let _ = retrieved;
}

#[test]
fn test_exporter_policy_per_signal() {
    let p_logs = get_exporter_policy(Signal::Logs).expect("logs");
    let p_traces = get_exporter_policy(Signal::Traces).expect("traces");
    let p_metrics = get_exporter_policy(Signal::Metrics).expect("metrics");
    let _ = (p_logs, p_traces, p_metrics);
}

#[test]
fn test_exporter_policy_retries_default_zero() {
    let policy = ExporterPolicy::default();
    assert_eq!(policy.retries, 0, "default retries should be 0");
}

#[test]
fn test_exporter_policy_fail_open_default_true() {
    let policy = ExporterPolicy::default();
    assert!(policy.fail_open, "default should fail open");
}
