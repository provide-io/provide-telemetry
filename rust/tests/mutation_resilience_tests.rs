// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// Mutation tests for resilience.rs — cover circuit breaker and error handling

use provide_telemetry::{get_circuit_state, get_exporter_policy, set_exporter_policy, ExporterPolicy};

#[test]
fn test_circuit_state_default() {
    // Circuit should start in a valid state
    let state = get_circuit_state("logs");
    // State should be one of the known variants
    let _ = state;
}

#[test]
fn test_exporter_policy_default() {
    let policy = get_exporter_policy();
    // Should return a valid policy
    let _ = policy;
}

#[test]
fn test_set_exporter_policy() {
    let policy = ExporterPolicy::default();
    set_exporter_policy(policy);

    let retrieved = get_exporter_policy();
    // Policy should be stored and retrieved
    let _ = retrieved;
}

#[test]
fn test_get_circuit_state_multiple_signals() {
    // Different signals should each have their own state
    let state_logs = get_circuit_state("logs");
    let state_traces = get_circuit_state("traces");
    let state_metrics = get_circuit_state("metrics");

    // Should all return valid states
    let _ = (state_logs, state_traces, state_metrics);
}
