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
const CIRCUIT_BASE_COOLDOWN_SECS: f64 = 30.0;
const CIRCUIT_MAX_COOLDOWN_SECS: f64 = 1024.0;

/// Compute exponential backoff cooldown for the circuit breaker.
///
/// cooldown = min(30s * 2^open_count, 1024s)
fn circuit_cooldown(open_count: u32) -> Duration {
    let secs =
        (CIRCUIT_BASE_COOLDOWN_SECS * 2f64.powi(open_count as i32)).min(CIRCUIT_MAX_COOLDOWN_SECS);
    Duration::from_secs_f64(secs)
}

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
    /// True while a half-open probe is in flight.
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

/// Return the current circuit state as `(state_name, open_count, remaining_cooldown_secs)`.
///
/// Possible state names:
/// - `"closed"` — circuit is healthy, requests pass through.
/// - `"open"` — circuit is tripped, cooldown has not yet elapsed.
/// - `"half-open"` — cooldown elapsed, one probe is permitted.
pub fn get_circuit_state(signal: Signal) -> Result<(String, u32, f64), TelemetryError> {
    let state = circuits()
        .lock()
        .expect("circuit lock poisoned")
        .get(&signal)
        .cloned()
        .ok_or_else(|| TelemetryError::new("unknown signal"))?;
    if state.consecutive_timeouts >= CIRCUIT_BREAKER_THRESHOLD {
        let cooldown = circuit_cooldown(state.open_count);
        let remaining = state
            .tripped_at
            .map(|instant| cooldown.saturating_sub(instant.elapsed()).as_secs_f64())
            .unwrap_or(0.0);
        if remaining > 0.0 {
            return Ok(("open".to_string(), state.open_count, remaining));
        }
        // Cooldown elapsed: allow half-open if no probe is already in flight.
        if !state.half_open_probing {
            return Ok(("half-open".to_string(), state.open_count, 0.0));
        }
        // Probe already in flight: treat as open with zero remaining cooldown.
        return Ok(("open".to_string(), state.open_count, 0.0));
    }
    Ok(("closed".to_string(), state.open_count, 0.0))
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

    // Check circuit state before attempting the operation.
    let (circuit_status, _, _) = get_circuit_state(signal)?;
    let is_half_open_probe = match circuit_status.as_str() {
        "open" => {
            // Circuit is open and cooldown has not elapsed — reject immediately.
            if policy.fail_open {
                return Ok(None);
            }
            return Err(TelemetryError::new("circuit breaker open"));
        }
        "half-open" => {
            // Allow one probe through; mark the probe as in-flight.
            if let Some(s) = circuits()
                .lock()
                .expect("circuit lock poisoned")
                .get_mut(&signal)
            {
                s.half_open_probing = true;
            }
            true
        }
        _ => false, // "closed"
    };

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
                let mut circuit_lock = circuits().lock().expect("circuit lock poisoned");
                if let Some(state) = circuit_lock.get_mut(&signal) {
                    state.consecutive_timeouts = 0;
                    if is_half_open_probe {
                        // Successful probe: reset the circuit breaker.
                        state.open_count = state.open_count.saturating_sub(1);
                        state.half_open_probing = false;
                        state.tripped_at = None;
                    }
                }
                return Ok(Some(value));
            }
            Err(err) => {
                record_export_failure(signal);
                let mut circuit_lock = circuits().lock().expect("circuit lock poisoned");
                if let Some(state) = circuit_lock.get_mut(&signal) {
                    if is_half_open_probe {
                        // Failed probe: re-trip the circuit breaker.
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
    fn resilience_test_exponential_backoff_cooldown() {
        // open_count=0 → 30s, =1 → 60s, =5 → 960s, =6 → capped at 1024s.
        assert_eq!(circuit_cooldown(0), Duration::from_secs_f64(30.0));
        assert_eq!(circuit_cooldown(1), Duration::from_secs_f64(60.0));
        assert_eq!(circuit_cooldown(5), Duration::from_secs_f64(960.0));
        assert_eq!(circuit_cooldown(6), Duration::from_secs_f64(1024.0));
        assert_eq!(circuit_cooldown(10), Duration::from_secs_f64(1024.0));
    }

    #[test]
    fn resilience_test_get_circuit_state_distinguishes_open_and_half_open() {
        let _guard = acquire_test_state_lock();
        _reset_resilience_for_tests();

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

        {
            // open_count=2 → cooldown = 30 * 2^2 = 120s; expire it by going back 121s.
            let elapsed_cooldown = circuit_cooldown(2) + Duration::from_secs(1);
            let mut lock = circuits().lock().expect("circuit lock poisoned");
            let state = lock
                .get_mut(&Signal::Logs)
                .expect("logs state should exist");
            state.tripped_at = Some(Instant::now() - elapsed_cooldown);
        }
        // After cooldown, no probe is in flight → half-open.
        let half_open = get_circuit_state(Signal::Logs).expect("state should exist");
        assert_eq!(half_open.0, "half-open");
        assert_eq!(half_open.1, 2);
        assert_eq!(half_open.2, 0.0);
    }

    #[test]
    fn resilience_test_half_open_probe_success_resets_circuit() {
        let _guard = acquire_test_state_lock();
        _reset_resilience_for_tests();
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("runtime");

        // Trip the circuit with open_count=1; expire cooldown.
        {
            let mut lock = circuits().lock().expect("circuit lock poisoned");
            let state = lock.get_mut(&Signal::Logs).expect("logs state");
            state.consecutive_timeouts = CIRCUIT_BREAKER_THRESHOLD;
            state.open_count = 1;
            state.tripped_at = Some(Instant::now() - circuit_cooldown(1) - Duration::from_secs(1));
        }

        // Circuit should be half-open now.
        let (state_name, open_count, _) =
            get_circuit_state(Signal::Logs).expect("state should exist");
        assert_eq!(state_name, "half-open");
        assert_eq!(open_count, 1);

        // Successful probe transitions to closed.
        let result = runtime.block_on(async {
            run_with_resilience(Signal::Logs, || async { Ok::<u32, TelemetryError>(42) }).await
        });
        assert!(result.expect("probe should succeed").is_some());

        let (state_after, open_after, _) =
            get_circuit_state(Signal::Logs).expect("state should exist");
        assert_eq!(state_after, "closed");
        assert_eq!(
            open_after, 0,
            "open_count should decrement after successful probe"
        );
    }

    #[test]
    fn resilience_test_half_open_probe_failure_retrips_circuit() {
        let _guard = acquire_test_state_lock();
        _reset_resilience_for_tests();
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("runtime");

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

        // Trip the circuit with open_count=1; expire cooldown.
        {
            let mut lock = circuits().lock().expect("circuit lock poisoned");
            let state = lock.get_mut(&Signal::Logs).expect("logs state");
            state.consecutive_timeouts = CIRCUIT_BREAKER_THRESHOLD;
            state.open_count = 1;
            state.tripped_at = Some(Instant::now() - circuit_cooldown(1) - Duration::from_secs(1));
        }

        // Failing probe should re-trip and increment open_count.
        let before_open_count = get_circuit_state(Signal::Logs).expect("state").1;
        let _ = runtime.block_on(async {
            run_with_resilience(Signal::Logs, || async {
                Err::<u32, _>(TelemetryError::new("probe fail"))
            })
            .await
        });

        let (state_after, open_after, _) =
            get_circuit_state(Signal::Logs).expect("state should exist");
        assert_eq!(state_after, "open");
        assert_eq!(
            open_after,
            before_open_count + 1,
            "open_count should increment after failed probe"
        );
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
