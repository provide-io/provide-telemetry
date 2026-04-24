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

fn default_policies_mutex() -> Mutex<BTreeMap<Signal, ExporterPolicy>> {
    Mutex::new(BTreeMap::from([
        (Signal::Logs, ExporterPolicy::default()),
        (Signal::Traces, ExporterPolicy::default()),
        (Signal::Metrics, ExporterPolicy::default()),
    ]))
}

fn policies() -> &'static Mutex<BTreeMap<Signal, ExporterPolicy>> {
    POLICIES.get_or_init(default_policies_mutex)
}

fn default_circuits_mutex() -> Mutex<BTreeMap<Signal, CircuitState>> {
    Mutex::new(BTreeMap::from([
        (Signal::Logs, CircuitState::default()),
        (Signal::Traces, CircuitState::default()),
        (Signal::Metrics, CircuitState::default()),
    ]))
}

fn circuits() -> &'static Mutex<BTreeMap<Signal, CircuitState>> {
    CIRCUITS.get_or_init(default_circuits_mutex)
}

fn backoff_duration(backoff_seconds: f64, has_tokio_reactor: bool) -> Option<Duration> {
    if backoff_seconds <= 0.0 || !has_tokio_reactor {
        None
    } else {
        Some(Duration::from_secs_f64(backoff_seconds))
    }
}

async fn wait_before_retry(
    signal: Signal,
    attempt: u32,
    backoff_seconds: f64,
    has_tokio_reactor: bool,
) {
    if attempt == 0 {
        return;
    }
    if let Some(backoff) = backoff_duration(backoff_seconds, has_tokio_reactor) {
        tokio::time::sleep(backoff).await;
    }
    increment_retries(signal, 1);
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
    let policy_lock = policies().lock().expect("policy lock poisoned");
    match policy_lock.get(&signal).cloned() {
        Some(policy) => Ok(policy),
        None => Err(TelemetryError::new("unknown signal")),
    }
}

pub fn get_circuit_state(signal: Signal) -> Result<(String, u32, f64), TelemetryError> {
    let circuits = circuits().lock().expect("circuit lock poisoned");
    let state = match circuits.get(&signal).cloned() {
        Some(state) => state,
        None => return Err(TelemetryError::new("unknown signal")),
    };
    Ok(describe_circuit_state(&state))
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
    // tokio::time::timeout / sleep require an active tokio reactor. When the
    // caller is the OTel SDK's dedicated BatchProcessor thread (which is NOT
    // a tokio runtime), the timeout wrapper would panic with "there is no
    // reactor running". Detect that case and fall through to a plain await:
    // the underlying HTTP exporter still has its own timeout from
    // SpanExporter::with_timeout, so the operation cannot hang forever.
    let has_tokio_reactor = tokio::runtime::Handle::try_current().is_ok();
    let timeout_active = if timeout.is_zero() {
        false
    } else {
        has_tokio_reactor
    };
    // Circuit-breaker gate is only consulted when timeout enforcement is on,
    // matching Python (resilience.py:177) and Go (resilience.go:170). When
    // timeout=0 the policy explicitly opts out of timeout-driven failure
    // accounting, so the breaker has no signal to act on.
    let should_probe = if timeout_active {
        _check_and_start_probe_for_wrappers(signal)
    } else {
        false
    };
    if should_probe {
        return if policy.fail_open {
            Ok(None)
        } else {
            Err(circuit_open_err())
        };
    }

    let max_attempts = policy.retries + 1;
    let mut last_err: Option<E> = None;
    let mut attempt = 0;
    while attempt < max_attempts {
        wait_before_retry(signal, attempt, policy.backoff_seconds, has_tokio_reactor).await;

        let started = Instant::now();
        let (result, wrapper_timeout) = if !timeout_active {
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
                let is_timeout = if wrapper_timeout {
                    true
                } else {
                    is_sdk_timeout(&err)
                };
                _record_circuit_failure_for_wrappers(signal, is_timeout);
                last_err = Some(err);
            }
        }
        attempt += 1;
    }

    if policy.fail_open {
        Ok(None)
    } else {
        // Safe: max_attempts >= 1, so the loop body has run at least once and
        // populated last_err on any error path that escapes the loop.
        Err(last_err.expect("retry loop ran at least once"))
    }
}

fn cooldown_remaining(tripped_at: Option<Instant>) -> f64 {
    match tripped_at {
        Some(instant) => CIRCUIT_COOLDOWN
            .saturating_sub(instant.elapsed())
            .as_secs_f64(),
        None => 0.0,
    }
}

fn describe_circuit_state(state: &CircuitState) -> (String, u32, f64) {
    if state.half_open_probing {
        return ("half-open".to_string(), state.open_count, 0.0);
    }
    if state.consecutive_timeouts >= CIRCUIT_BREAKER_THRESHOLD {
        let remaining = cooldown_remaining(state.tripped_at);
        if remaining > 0.0 {
            return ("open".to_string(), state.open_count, remaining);
        }
        return ("half-open".to_string(), state.open_count, 0.0);
    }
    ("closed".to_string(), state.open_count, 0.0)
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

/// Record a failed export attempt into the shared circuit-breaker state.
/// Called by resilient exporter wrappers in `otel/resilient.rs` which cannot
/// use `run_with_resilience` directly (RPIT futures prevent `Fn() -> Fut`).
/// Handles both normal (increment + trip) and half-open probe (re-open) paths.
///
/// `is_timeout` discriminates timeout failures from other errors. Only
/// timeouts increment the breaker counter; other failures reset it. Mirrors
/// Python (resilience.py:154), Go (resilience.go:118), and TS (resilience.ts:180).
pub(crate) fn _record_circuit_failure_for_wrappers(signal: Signal, is_timeout: bool) {
    let mut circuit_lock = circuits().lock().expect("circuit lock poisoned");
    let Some(state) = circuit_lock.get_mut(&signal) else {
        return;
    };
    if state.half_open_probing {
        state.half_open_probing = false;
        state.open_count += 1;
        state.tripped_at = Some(Instant::now());
        return;
    }
    if !is_timeout {
        state.consecutive_timeouts = 0;
        return;
    }
    state.consecutive_timeouts += 1;
    if state.consecutive_timeouts >= CIRCUIT_BREAKER_THRESHOLD {
        state.open_count += 1;
        state.tripped_at = Some(Instant::now());
    }
}

/// Record a successful export attempt — reset consecutive_timeouts so the
/// circuit can close again. Handles half-open probe close. Called by resilient
/// exporter wrappers.
pub(crate) fn _record_circuit_success_for_wrappers(signal: Signal) {
    let mut circuit_lock = circuits().lock().expect("circuit lock poisoned");
    let Some(state) = circuit_lock.get_mut(&signal) else {
        return;
    };
    if state.half_open_probing {
        state.half_open_probing = false;
    }
    state.consecutive_timeouts = 0;
}

/// Check whether the circuit for `signal` should be entered for a probe attempt,
/// and if so mark the probe as in-flight. Returns `true` if the circuit is open
/// (fully — cooldown still active) or if a probe is already running (concurrent
/// callers should be rejected). Returns `false` if the operation may proceed
/// (either circuit closed, or cooldown elapsed and this call starts the probe).
pub(crate) fn _check_and_start_probe_for_wrappers(signal: Signal) -> bool {
    let mut circuit_lock = circuits().lock().expect("circuit lock poisoned");
    let Some(state) = circuit_lock.get_mut(&signal) else {
        return false;
    };
    if state.consecutive_timeouts < CIRCUIT_BREAKER_THRESHOLD {
        return false;
    }
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

pub fn _clear_resilience_state_for_tests() {
    policies().lock().expect("policy lock poisoned").clear();
    circuits().lock().expect("circuit lock poisoned").clear();
}

#[cfg(test)]
#[path = "resilience_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "resilience_inner_callback_tests.rs"]
mod inner_callback_tests;

#[cfg(test)]
#[path = "resilience_state_tests.rs"]
mod state_tests;
