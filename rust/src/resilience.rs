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

pub(crate) const CIRCUIT_BREAKER_THRESHOLD: u32 = 3;
pub(crate) const CIRCUIT_COOLDOWN: Duration = Duration::from_secs(30);

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
    /// True while exactly one half-open probe is in flight.
    half_open_probing: bool,
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
    // A probe is in flight — report half-open regardless of cooldown.
    if state.half_open_probing {
        return Ok(("half-open".to_string(), state.open_count, 0.0));
    }
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
        // Cooldown elapsed but no probe started yet — half-open.
        return Ok(("half-open".to_string(), state.open_count, 0.0));
    }
    Ok(("closed".to_string(), state.open_count, 0.0))
}

/// Generic resilience primitive: wraps `operation` in the per-signal
/// retry/timeout/circuit-breaker policy. Used by both [`run_with_resilience`]
/// (which works in `TelemetryError`) and the OTel exporter wrappers in
/// `otel/resilient.rs` (which work in `OTelSdkResult`). The error-type
/// callbacks let each caller plug in its own variants — there is exactly one
/// loop body, so retry/timeout/backoff/circuit semantics cannot drift between
/// the two callsites.
///
/// * `timeout_err(d)` — synthesise the error returned when the wrapper-imposed
///   `tokio::time::timeout` fires (operation never completed within `d`).
/// * `is_sdk_timeout(&e)` — return true for SDK-reported timeouts that should
///   also count toward the circuit breaker. Returns false for `TelemetryError`
///   (which carries no timeout discriminator).
/// * `circuit_open_err()` — synthesise the error returned when the breaker
///   refuses an attempt (fail_open=false path only).
pub(crate) async fn run_with_resilience_inner<F, Fut, T, E>(
    signal: Signal,
    policy: &ExporterPolicy,
    operation: F,
    timeout_err: impl Fn(Duration) -> E,
    is_sdk_timeout: impl Fn(&E) -> bool,
    circuit_open_err: impl Fn() -> E,
) -> Result<Option<T>, E>
where
    F: Fn() -> Fut,
    Fut: Future<Output = Result<T, E>>,
{
    let timeout = Duration::from_secs_f64(policy.timeout_seconds.max(0.0));
    // Circuit-breaker gate is only consulted when timeout enforcement is on,
    // matching Python (resilience.py:177) and Go (resilience.go:170). When
    // timeout=0 the policy explicitly opts out of timeout-driven failure
    // accounting, so the breaker has no signal to act on.
    if !timeout.is_zero() && _check_and_start_probe_for_wrappers(signal) {
        return if policy.fail_open {
            Ok(None)
        } else {
            Err(circuit_open_err())
        };
    }

    let max_attempts = policy.retries + 1;
    let mut last_err: Option<E> = None;

    for attempt in 0..max_attempts {
        if attempt > 0 {
            if policy.backoff_seconds > 0.0 {
                tokio::time::sleep(Duration::from_secs_f64(policy.backoff_seconds)).await;
            }
            increment_retries(signal, 1);
        }

        let started = Instant::now();
        let (result, wrapper_timeout) = if timeout.is_zero() {
            (operation().await, false)
        } else {
            match tokio::time::timeout(timeout, operation()).await {
                Ok(inner) => (inner, false),
                Err(_) => (Err(timeout_err(timeout)), true),
            }
        };

        match result {
            Ok(value) => {
                record_export_latency(signal, started.elapsed().as_secs_f64() * 1000.0);
                _record_circuit_success_for_wrappers(signal);
                return Ok(Some(value));
            }
            Err(err) => {
                record_export_failure(signal);
                // Only timeouts contribute to the breaker counter; other
                // failures reset it. Mirrors Python (resilience.py:154),
                // Go (resilience.go:118), and TS (resilience.ts:180).
                let is_timeout = wrapper_timeout || is_sdk_timeout(&err);
                _record_circuit_failure_for_wrappers(signal, is_timeout);
                last_err = Some(err);
            }
        }
    }

    if policy.fail_open {
        Ok(None)
    } else {
        // Safe: max_attempts >= 1, so the loop body has run at least once and
        // populated last_err on any error path that escapes the loop.
        Err(last_err.expect("retry loop ran at least once"))
    }
}

pub async fn run_with_resilience<F, Fut, T>(
    signal: Signal,
    operation: F,
) -> Result<Option<T>, TelemetryError>
where
    F: Fn() -> Fut,
    Fut: Future<Output = Result<T, TelemetryError>>,
{
    let policy = get_exporter_policy(signal)?;
    run_with_resilience_inner(
        signal,
        &policy,
        operation,
        |_| TelemetryError::new("operation timed out"),
        |_| false,
        || TelemetryError::new("circuit breaker open"),
    )
    .await
}

/// Record a successful export attempt — reset consecutive_timeouts so the
/// circuit can close again. Handles half-open probe close. Called by resilient
/// exporter wrappers.
pub(crate) fn _record_circuit_success_for_wrappers(signal: Signal) {
    if let Some(state) = circuits()
        .lock()
        .expect("circuit lock poisoned")
        .get_mut(&signal)
    {
        if state.half_open_probing {
            // Successful probe — close the breaker.
            state.half_open_probing = false;
            state.consecutive_timeouts = 0;
        } else {
            state.consecutive_timeouts = 0;
        }
    }
}

/// Check whether the circuit for `signal` should be entered for a probe attempt,
/// and if so mark the probe as in-flight. Returns `true` if the circuit is open
/// (fully — cooldown still active) or if a probe is already running (concurrent
/// callers should be rejected). Returns `false` if the operation may proceed
/// (either circuit closed, or cooldown elapsed and this call starts the probe).
pub(crate) fn _check_and_start_probe_for_wrappers(signal: Signal) -> bool {
    let mut circuit_lock = circuits().lock().expect("circuit lock poisoned");
    if let Some(state) = circuit_lock.get_mut(&signal) {
        if state.consecutive_timeouts >= CIRCUIT_BREAKER_THRESHOLD {
            let cooldown_active = state
                .tripped_at
                .map(|instant| instant.elapsed() < CIRCUIT_COOLDOWN)
                .unwrap_or(false);
            if cooldown_active {
                return true; // Still open — reject.
            }
            if state.half_open_probing {
                return true; // Probe already in flight — reject concurrent caller.
            }
            // Cooldown elapsed, no probe running — start one.
            state.half_open_probing = true;
        }
    }
    false
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

#[cfg(test)]
#[path = "resilience_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "resilience_inner_callback_tests.rs"]
mod inner_callback_tests;
