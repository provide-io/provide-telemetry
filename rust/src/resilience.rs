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

/// Sibling loop: the OTel exporter wrappers in `otel/resilient.rs` inline the
/// same retry/timeout/circuit-breaker body because `PushMetricExporter` takes
/// a non-`Clone` batch reference and the exporter traits return `impl Future`
/// of `OTelSdkResult`, which don't fit `Fn() -> Fut` / `TelemetryError` here.
/// Any change to the policy loop semantics must be applied in both files.
pub async fn run_with_resilience<F, Fut, T>(
    signal: Signal,
    operation: F,
) -> Result<Option<T>, TelemetryError>
where
    F: Fn() -> Fut,
    Fut: Future<Output = Result<T, TelemetryError>>,
{
    let policy = get_exporter_policy(signal)?;
    // Circuit breaker gate: check state and, if applicable, start a half-open probe.
    {
        let mut circuit_lock = circuits().lock().expect("circuit lock poisoned");
        if let Some(state) = circuit_lock.get_mut(&signal) {
            if state.consecutive_timeouts >= CIRCUIT_BREAKER_THRESHOLD {
                let cooldown_active = state
                    .tripped_at
                    .map(|instant| instant.elapsed() < CIRCUIT_COOLDOWN)
                    .unwrap_or(false);
                if cooldown_active {
                    // Still within cooldown — fully open, reject.
                    if policy.fail_open {
                        return Ok(None);
                    }
                    return Err(TelemetryError::new("circuit breaker open"));
                }
                // Cooldown has elapsed — enter half-open.
                if state.half_open_probing {
                    // A probe is already in flight — reject concurrent callers.
                    if policy.fail_open {
                        return Ok(None);
                    }
                    return Err(TelemetryError::new("circuit breaker open"));
                }
                // Mark one probe in flight.
                state.half_open_probing = true;
            }
        }
    }

    let timeout = Duration::from_secs_f64(policy.timeout_seconds.max(0.0));
    let max_attempts = policy.retries + 1;
    let mut last_err = TelemetryError::new("no attempts made");

    for attempt in 0..max_attempts {
        if attempt > 0 {
            if policy.backoff_seconds > 0.0 {
                let backoff = Duration::from_secs_f64(policy.backoff_seconds);
                tokio::time::sleep(backoff).await;
            }
            increment_retries(signal, 1);
        }

        let started = Instant::now();
        let result = if timeout.is_zero() {
            operation().await
        } else {
            match tokio::time::timeout(timeout, operation()).await {
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
                    if state.half_open_probing {
                        // Successful probe — close the breaker.
                        state.half_open_probing = false;
                        state.consecutive_timeouts = 0;
                    } else {
                        state.consecutive_timeouts = 0;
                    }
                }
                return Ok(Some(value));
            }
            Err(err) => {
                record_export_failure(signal);
                let mut circuit_lock = circuits().lock().expect("circuit lock poisoned");
                if let Some(state) = circuit_lock.get_mut(&signal) {
                    if state.half_open_probing {
                        // Failed probe — clear probe flag and re-open the breaker.
                        state.half_open_probing = false;
                        state.open_count += 1;
                        state.tripped_at = Some(Instant::now());
                    } else {
                        state.consecutive_timeouts += 1;
                        if state.consecutive_timeouts >= CIRCUIT_BREAKER_THRESHOLD {
                            state.open_count += 1;
                            state.tripped_at = Some(Instant::now());
                        }
                    }
                }
                last_err = err;
            }
        }
    }

    if policy.fail_open {
        Ok(None)
    } else {
        Err(last_err)
    }
}

/// Record a failed export attempt into the shared circuit-breaker state.
/// Called by resilient exporter wrappers in `otel/resilient.rs` which cannot
/// use `run_with_resilience` directly (RPIT futures prevent `Fn() -> Fut`).
/// Handles both normal (increment + trip) and half-open probe (re-open) paths.
pub(crate) fn _record_circuit_failure_for_wrappers(signal: Signal) {
    let mut circuit_lock = circuits().lock().expect("circuit lock poisoned");
    if let Some(state) = circuit_lock.get_mut(&signal) {
        if state.half_open_probing {
            // Failed probe — clear probe flag and re-open the breaker.
            state.half_open_probing = false;
            state.open_count += 1;
            state.tripped_at = Some(Instant::now());
        } else {
            state.consecutive_timeouts += 1;
            if state.consecutive_timeouts >= CIRCUIT_BREAKER_THRESHOLD {
                state.open_count += 1;
                state.tripped_at = Some(Instant::now());
            }
        }
    }
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
mod tests {
    use super::*;
    use crate::testing::acquire_test_state_lock;

    #[test]
    fn resilience_test_get_circuit_state_closed_open_half_open() {
        let _guard = acquire_test_state_lock();
        _reset_resilience_for_tests();

        // Closed: default state.
        let closed = get_circuit_state(Signal::Logs).expect("state should exist");
        assert_eq!(closed.0, "closed");
        assert_eq!(closed.1, 0);
        assert_eq!(closed.2, 0.0);

        // Open: threshold reached, cooldown still active.
        {
            let mut lock = circuits().lock().expect("circuit lock poisoned");
            let state = lock
                .get_mut(&Signal::Logs)
                .expect("logs state should exist");
            state.consecutive_timeouts = CIRCUIT_BREAKER_THRESHOLD;
            state.open_count = 2;
            state.tripped_at = Some(Instant::now());
        }
        let open = get_circuit_state(Signal::Logs).expect("state should exist");
        assert_eq!(open.0, "open");
        assert_eq!(open.1, 2);
        assert!(open.2 > 0.0);

        // Half-open: cooldown elapsed, no probe in flight yet.
        {
            let mut lock = circuits().lock().expect("circuit lock poisoned");
            let state = lock
                .get_mut(&Signal::Logs)
                .expect("logs state should exist");
            state.tripped_at = Some(Instant::now() - CIRCUIT_COOLDOWN - Duration::from_secs(1));
            state.half_open_probing = false;
        }
        let half_open = get_circuit_state(Signal::Logs).expect("state should exist");
        assert_eq!(half_open.0, "half-open");
        assert_eq!(half_open.1, 2);
        assert_eq!(half_open.2, 0.0);

        // Half-open: probe explicitly in flight (half_open_probing=true).
        {
            let mut lock = circuits().lock().expect("circuit lock poisoned");
            let state = lock
                .get_mut(&Signal::Logs)
                .expect("logs state should exist");
            state.half_open_probing = true;
        }
        let probing = get_circuit_state(Signal::Logs).expect("state should exist");
        assert_eq!(probing.0, "half-open");
        assert_eq!(probing.1, 2);
        assert_eq!(probing.2, 0.0);
    }

    #[test]
    fn resilience_test_half_open_probe_success_closes_breaker() {
        let _guard = acquire_test_state_lock();
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("runtime");
        _reset_resilience_for_tests();
        set_exporter_policy(
            Signal::Logs,
            ExporterPolicy {
                retries: 0,
                backoff_seconds: 0.0,
                timeout_seconds: 0.0,
                fail_open: true,
                allow_blocking_in_event_loop: false,
            },
        )
        .expect("policy should set");

        // Trip the breaker.
        {
            let mut lock = circuits().lock().expect("circuit lock poisoned");
            let state = lock
                .get_mut(&Signal::Logs)
                .expect("logs state should exist");
            state.consecutive_timeouts = CIRCUIT_BREAKER_THRESHOLD;
            state.open_count = 1;
            // Expire the cooldown so the breaker is ready for a half-open probe.
            state.tripped_at = Some(Instant::now() - CIRCUIT_COOLDOWN - Duration::from_secs(1));
        }

        // First call after cooldown: probe is allowed through, and succeeds.
        let result = runtime.block_on(async {
            run_with_resilience(Signal::Logs, || async { Ok::<_, TelemetryError>(42u32) }).await
        });
        assert_eq!(result.unwrap(), Some(42u32));

        // After a successful probe the breaker must be closed.
        let state_after = get_circuit_state(Signal::Logs).expect("state should exist");
        assert_eq!(state_after.0, "closed");
        assert_eq!(state_after.2, 0.0);
    }

    #[test]
    fn resilience_test_half_open_probe_failure_reopens_breaker() {
        let _guard = acquire_test_state_lock();
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("runtime");
        _reset_resilience_for_tests();
        set_exporter_policy(
            Signal::Logs,
            ExporterPolicy {
                retries: 0,
                backoff_seconds: 0.0,
                timeout_seconds: 0.0,
                fail_open: true,
                allow_blocking_in_event_loop: false,
            },
        )
        .expect("policy should set");

        // Trip the breaker with expired cooldown — ready for half-open.
        {
            let mut lock = circuits().lock().expect("circuit lock poisoned");
            let state = lock
                .get_mut(&Signal::Logs)
                .expect("logs state should exist");
            state.consecutive_timeouts = CIRCUIT_BREAKER_THRESHOLD;
            state.open_count = 1;
            state.tripped_at = Some(Instant::now() - CIRCUIT_COOLDOWN - Duration::from_secs(1));
        }

        // The probe call fails — breaker should re-open.
        let result = runtime.block_on(async {
            run_with_resilience(Signal::Logs, || async {
                Err::<(), _>(TelemetryError::new("probe boom"))
            })
            .await
        });
        assert!(result.unwrap().is_none()); // fail_open=true

        // Breaker must be open again.
        let state_after = get_circuit_state(Signal::Logs).expect("state should exist");
        assert_eq!(state_after.0, "open");
        assert!(state_after.2 > 0.0, "cooldown must be active after re-open");
    }

    #[test]
    fn resilience_test_concurrent_callers_during_probe_are_rejected() {
        let _guard = acquire_test_state_lock();
        _reset_resilience_for_tests();
        set_exporter_policy(
            Signal::Logs,
            ExporterPolicy {
                retries: 0,
                backoff_seconds: 0.0,
                timeout_seconds: 0.0,
                fail_open: true,
                allow_blocking_in_event_loop: false,
            },
        )
        .expect("policy should set");

        // Manually put the breaker into "probe in flight" state.
        {
            let mut lock = circuits().lock().expect("circuit lock poisoned");
            let state = lock
                .get_mut(&Signal::Logs)
                .expect("logs state should exist");
            state.consecutive_timeouts = CIRCUIT_BREAKER_THRESHOLD;
            state.open_count = 1;
            state.tripped_at = Some(Instant::now() - CIRCUIT_COOLDOWN - Duration::from_secs(1));
            state.half_open_probing = true; // Probe already in flight.
        }

        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("runtime");

        // Concurrent caller should be rejected (fail-open returns Ok(None)).
        let result = runtime.block_on(async {
            run_with_resilience(Signal::Logs, || async { Ok::<_, TelemetryError>(99u32) }).await
        });
        assert_eq!(
            result.unwrap(),
            None,
            "concurrent caller during probe should be rejected as Ok(None) when fail_open"
        );
    }

    #[test]
    fn resilience_test_concurrent_callers_during_probe_fail_closed_returns_error() {
        let _guard = acquire_test_state_lock();
        _reset_resilience_for_tests();
        set_exporter_policy(
            Signal::Logs,
            ExporterPolicy {
                retries: 0,
                backoff_seconds: 0.0,
                timeout_seconds: 0.0,
                fail_open: false,
                allow_blocking_in_event_loop: false,
            },
        )
        .expect("policy should set");

        // Probe already in flight.
        {
            let mut lock = circuits().lock().expect("circuit lock poisoned");
            let state = lock
                .get_mut(&Signal::Logs)
                .expect("logs state should exist");
            state.consecutive_timeouts = CIRCUIT_BREAKER_THRESHOLD;
            state.open_count = 1;
            state.tripped_at = Some(Instant::now() - CIRCUIT_COOLDOWN - Duration::from_secs(1));
            state.half_open_probing = true;
        }

        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("runtime");

        let err = runtime
            .block_on(async {
                run_with_resilience(Signal::Logs, || async { Ok::<_, TelemetryError>(99u32) }).await
            })
            .expect_err("fail-closed + probe in flight should return Err");
        assert_eq!(err.message, "circuit breaker open");
    }

    #[test]
    fn resilience_test_fail_closed_returns_error_and_reset_helper_restores_defaults() {
        let _guard = acquire_test_state_lock();
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("runtime");
        _reset_resilience_for_tests();
        set_exporter_policy(
            Signal::Logs,
            ExporterPolicy {
                retries: 1,
                backoff_seconds: 0.0,
                timeout_seconds: 0.0,
                fail_open: false,
                allow_blocking_in_event_loop: false,
            },
        )
        .expect("policy should set");

        let err = runtime
            .block_on(async {
                run_with_resilience(Signal::Logs, || async {
                    Err::<(), _>(TelemetryError::new("boom"))
                })
                .await
            })
            .expect_err("fail-closed policy should return the exporter error");
        assert_eq!(err.message, "boom");

        _reset_resilience_for_tests();
        let policy = get_exporter_policy(Signal::Logs).expect("policy should exist");
        assert_eq!(policy, ExporterPolicy::default());
        let state = get_circuit_state(Signal::Logs).expect("state should exist");
        assert_eq!(state.0, "closed");
        assert_eq!(state.1, 0);
    }
}
