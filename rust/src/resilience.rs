// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;
use std::future::Future;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use crate::errors::TelemetryError;
use crate::health::{increment_retries, record_export_failure, record_export_latency};
use crate::sampling::Signal;

const CIRCUIT_BREAKER_THRESHOLD: u32 = 3;
const CIRCUIT_COOLDOWN: Duration = Duration::from_secs(30);

#[derive(Clone, Debug, PartialEq)]
pub struct ExporterPolicy {
    pub retries: u32,
    pub backoff_seconds: f64,
    pub timeout_seconds: f64,
    pub fail_open: bool,
    pub allow_blocking_in_event_loop: bool,
}

impl Default for ExporterPolicy {
    fn default() -> Self {
        Self {
            retries: 0,
            backoff_seconds: 0.0,
            timeout_seconds: 10.0,
            fail_open: true,
            allow_blocking_in_event_loop: false,
        }
    }
}

#[derive(Clone, Debug, Default)]
struct CircuitState {
    consecutive_timeouts: u32,
    tripped_at: Option<Instant>,
    open_count: u32,
}

static POLICIES: OnceLock<Mutex<BTreeMap<Signal, ExporterPolicy>>> = OnceLock::new();
static CIRCUITS: OnceLock<Mutex<BTreeMap<Signal, CircuitState>>> = OnceLock::new();

fn policies() -> &'static Mutex<BTreeMap<Signal, ExporterPolicy>> {
    POLICIES.get_or_init(|| {
        Mutex::new(BTreeMap::from([
            (Signal::Logs, ExporterPolicy::default()),
            (Signal::Traces, ExporterPolicy::default()),
            (Signal::Metrics, ExporterPolicy::default()),
        ]))
    })
}

fn circuits() -> &'static Mutex<BTreeMap<Signal, CircuitState>> {
    CIRCUITS.get_or_init(|| {
        Mutex::new(BTreeMap::from([
            (Signal::Logs, CircuitState::default()),
            (Signal::Traces, CircuitState::default()),
            (Signal::Metrics, CircuitState::default()),
        ]))
    })
}

pub fn set_exporter_policy(
    signal: Signal,
    policy: ExporterPolicy,
) -> Result<ExporterPolicy, TelemetryError> {
    policies()
        .lock()
        .expect("policy lock poisoned")
        .insert(signal, policy.clone());
    Ok(policy)
}

pub fn get_exporter_policy(signal: Signal) -> Result<ExporterPolicy, TelemetryError> {
    policies()
        .lock()
        .expect("policy lock poisoned")
        .get(&signal)
        .cloned()
        .ok_or_else(|| TelemetryError::new("unknown signal"))
}

pub fn get_circuit_state(signal: Signal) -> Result<(String, u32, f64), TelemetryError> {
    let state = circuits()
        .lock()
        .expect("circuit lock poisoned")
        .get(&signal)
        .cloned()
        .ok_or_else(|| TelemetryError::new("unknown signal"))?;
    if state.consecutive_timeouts >= CIRCUIT_BREAKER_THRESHOLD {
        let remaining = state
            .tripped_at
            .map(|instant| {
                CIRCUIT_COOLDOWN
                    .saturating_sub(instant.elapsed())
                    .as_secs_f64()
            })
            .unwrap_or(0.0);
        if remaining > 0.0 {
            return Ok(("open".to_string(), state.open_count, remaining));
        }
    }
    Ok(("closed".to_string(), state.open_count, 0.0))
}

pub async fn run_with_resilience<F, T>(
    signal: Signal,
    operation: F,
) -> Result<Option<T>, TelemetryError>
where
    F: Future<Output = Result<T, TelemetryError>>,
{
    let policy = get_exporter_policy(signal)?;
    {
        let circuits = circuits().lock().expect("circuit lock poisoned");
        if let Some(state) = circuits.get(&signal) {
            if state.consecutive_timeouts >= CIRCUIT_BREAKER_THRESHOLD
                && state
                    .tripped_at
                    .map(|instant| instant.elapsed() < CIRCUIT_COOLDOWN)
                    .unwrap_or(false)
            {
                if policy.fail_open {
                    return Ok(None);
                }
                return Err(TelemetryError::new("circuit breaker open"));
            }
        }
    }

    let started = Instant::now();
    let timeout = Duration::from_secs_f64(policy.timeout_seconds.max(0.0));
    let result = if timeout.is_zero() {
        operation.await
    } else {
        match tokio::time::timeout(timeout, operation).await {
            Ok(inner) => inner,
            Err(_) => Err(TelemetryError::new("operation timed out")),
        }
    };

    match result {
        Ok(value) => {
            record_export_latency(signal, started.elapsed().as_secs_f64() * 1000.0);
            if let Some(state) = circuits()
                .lock()
                .expect("circuit lock poisoned")
                .get_mut(&signal)
            {
                state.consecutive_timeouts = 0;
            }
            Ok(Some(value))
        }
        Err(err) => {
            record_export_failure(signal);
            let mut circuit_lock = circuits().lock().expect("circuit lock poisoned");
            if let Some(state) = circuit_lock.get_mut(&signal) {
                state.consecutive_timeouts += 1;
                if state.consecutive_timeouts >= CIRCUIT_BREAKER_THRESHOLD {
                    state.open_count += 1;
                    state.tripped_at = Some(Instant::now());
                }
            }
            if policy.retries > 0 {
                increment_retries(signal, 1);
            }
            if policy.fail_open {
                Ok(None)
            } else {
                Err(err)
            }
        }
    }
}

pub fn _reset_resilience_for_tests() {
    *policies().lock().expect("policy lock poisoned") = BTreeMap::from([
        (Signal::Logs, ExporterPolicy::default()),
        (Signal::Traces, ExporterPolicy::default()),
        (Signal::Metrics, ExporterPolicy::default()),
    ]);
    *circuits().lock().expect("circuit lock poisoned") = BTreeMap::from([
        (Signal::Logs, CircuitState::default()),
        (Signal::Traces, CircuitState::default()),
        (Signal::Metrics, CircuitState::default()),
    ]);
}
