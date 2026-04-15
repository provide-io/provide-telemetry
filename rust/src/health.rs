// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::sync::{Mutex, OnceLock};

use crate::sampling::Signal;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HealthSnapshot {
    pub emitted_logs: u64,
    pub emitted_traces: u64,
    pub emitted_metrics: u64,
    pub dropped_logs: u64,
    pub dropped_traces: u64,
    pub dropped_metrics: u64,
    pub export_failures_logs: u64,
    pub export_failures_traces: u64,
    pub export_failures_metrics: u64,
    pub retries_logs: u64,
    pub retries_traces: u64,
    pub retries_metrics: u64,
    pub export_latency_ms_logs: f64,
    pub export_latency_ms_traces: f64,
    pub export_latency_ms_metrics: f64,
    pub async_blocking_risk_logs: u64,
    pub async_blocking_risk_traces: u64,
    pub async_blocking_risk_metrics: u64,
    pub circuit_state_logs: String,
    pub circuit_state_traces: String,
    pub circuit_state_metrics: String,
    pub circuit_open_count_logs: u64,
    pub circuit_open_count_traces: u64,
    pub circuit_open_count_metrics: u64,
    pub setup_error: Option<String>,
}

static HEALTH: OnceLock<Mutex<HealthSnapshot>> = OnceLock::new();

fn health() -> &'static Mutex<HealthSnapshot> {
    HEALTH.get_or_init(|| Mutex::new(HealthSnapshot::default()))
}

pub fn get_health_snapshot() -> HealthSnapshot {
    let mut snapshot = health().lock().expect("health lock poisoned").clone();
    if let Ok((state, count, _)) = crate::resilience::get_circuit_state(Signal::Logs) {
        snapshot.circuit_state_logs = state;
        snapshot.circuit_open_count_logs = count as u64;
    }
    if let Ok((state, count, _)) = crate::resilience::get_circuit_state(Signal::Traces) {
        snapshot.circuit_state_traces = state;
        snapshot.circuit_open_count_traces = count as u64;
    }
    if let Ok((state, count, _)) = crate::resilience::get_circuit_state(Signal::Metrics) {
        snapshot.circuit_state_metrics = state;
        snapshot.circuit_open_count_metrics = count as u64;
    }
    snapshot
}

pub fn increment_dropped(signal: Signal, amount: u64) {
    let mut snapshot = health().lock().expect("health lock poisoned");
    match signal {
        Signal::Logs => snapshot.dropped_logs += amount,
        Signal::Traces => snapshot.dropped_traces += amount,
        Signal::Metrics => snapshot.dropped_metrics += amount,
    }
}

pub fn increment_emitted(signal: Signal, amount: u64) {
    let mut snapshot = health().lock().expect("health lock poisoned");
    match signal {
        Signal::Logs => snapshot.emitted_logs += amount,
        Signal::Traces => snapshot.emitted_traces += amount,
        Signal::Metrics => snapshot.emitted_metrics += amount,
    }
}

pub fn increment_retries(signal: Signal, amount: u64) {
    let mut snapshot = health().lock().expect("health lock poisoned");
    match signal {
        Signal::Logs => snapshot.retries_logs += amount,
        Signal::Traces => snapshot.retries_traces += amount,
        Signal::Metrics => snapshot.retries_metrics += amount,
    }
}

pub fn record_export_failure(signal: Signal) {
    let mut snapshot = health().lock().expect("health lock poisoned");
    match signal {
        Signal::Logs => snapshot.export_failures_logs += 1,
        Signal::Traces => snapshot.export_failures_traces += 1,
        Signal::Metrics => snapshot.export_failures_metrics += 1,
    }
}

pub fn record_export_latency(signal: Signal, latency_ms: f64) {
    let mut snapshot = health().lock().expect("health lock poisoned");
    match signal {
        Signal::Logs => snapshot.export_latency_ms_logs = latency_ms.max(0.0),
        Signal::Traces => snapshot.export_latency_ms_traces = latency_ms.max(0.0),
        Signal::Metrics => snapshot.export_latency_ms_metrics = latency_ms.max(0.0),
    }
}

pub fn _reset_health_for_tests() {
    *health().lock().expect("health lock poisoned") = HealthSnapshot::default();
}
