// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Per-export resilience wrappers for OTel SDK exporters.
//!
//! ## Why this duplicates the loop in `resilience.rs`
//!
//! The generic [`crate::resilience::run_with_resilience`] requires
//! `F: Fn() -> Fut` with `Fut: Future<Output = Result<T, TelemetryError>>`.
//! Two concrete obstacles prevent straight reuse from the exporter traits:
//!
//! 1. `PushMetricExporter::export` receives `&ResourceMetrics` and the type
//!    does not implement `Clone`, so a `Fn` closure that clones the batch per
//!    retry cannot be constructed. `SpanData` and `LogRecord` *are* `Clone`,
//!    so a partial reuse (traces/logs only) would split the policy loop
//!    across three call sites instead of consolidating it — strictly worse
//!    for drift risk than the current single inline loop.
//! 2. The OTel result type is [`OTelSdkResult`] (`Result<(), OTelSdkError>`),
//!    not [`crate::errors::TelemetryError`], and the variants the SDK expects
//!    (`Timeout(Duration)`, `InternalFailure(String)`) would need bespoke
//!    mapping on every call site.
//!
//! Rather than refactor `run_with_resilience` to support `FnOnce` plus a
//! second generic error type (which would complicate the public API consumed
//! by non-exporter callers such as scheduled flush helpers), this module
//! inlines the same loop body and coordinates through the shared
//! `POLICIES` + `CIRCUITS` static maps in `resilience.rs`. The helper hooks
//! [`_record_circuit_failure_for_wrappers`] /
//! [`_record_circuit_success_for_wrappers`] keep the state-update logic in a
//! single place so the two loops cannot drift on that front.
//!
//! Invariant: any change to retry/backoff/timeout/circuit-breaker semantics
//! MUST be applied in both `run_with_resilience` *and* `run_resilience_loop`.
//! The existing test suite in this module exercises the same matrix of cases
//! as `tests/resilience/` (success, fail-open drop, fail-closed surface,
//! retries, circuit trip, shutdown/flush) to catch any divergence.
//!
//! The wrapper reads `ExporterPolicy` and circuit state on every `export()`
//! call, so hot-reloaded policies take effect immediately — the same guarantee
//! as `run_with_resilience`.

use std::fmt;
use std::time::{Duration, Instant};

use opentelemetry_sdk::error::{OTelSdkError, OTelSdkResult};
use opentelemetry_sdk::logs::{LogBatch, LogExporter};
use opentelemetry_sdk::metrics::data::ResourceMetrics;
use opentelemetry_sdk::metrics::exporter::PushMetricExporter;
use opentelemetry_sdk::metrics::Temporality;
use opentelemetry_sdk::trace::{SpanData, SpanExporter};
use opentelemetry_sdk::Resource;

use crate::health::{increment_retries, record_export_failure, record_export_latency};
use crate::resilience::{
    _check_and_start_probe_for_wrappers, _record_circuit_failure_for_wrappers,
    _record_circuit_success_for_wrappers, get_exporter_policy, ExporterPolicy,
};
use crate::sampling::Signal;

// ── Circuit-breaker helpers ───────────────────────────────────────────────────

/// Check the circuit for `signal`.  Returns `true` (caller must reject) when
/// the circuit is fully open (cooldown active) or a half-open probe is already
/// in flight.  Returns `false` when the caller may proceed; if the cooldown has
/// just elapsed this also marks the probe as in-flight.
fn circuit_gate(signal: Signal) -> bool {
    _check_and_start_probe_for_wrappers(signal)
}

/// Inform the shared circuit-breaker state and health counters about a failed
/// export attempt. `is_timeout` discriminates timeout failures from other
/// errors so the breaker only counts true timeouts (Python/Go/TS contract).
fn on_export_failure(signal: Signal, is_timeout: bool) {
    _record_circuit_failure_for_wrappers(signal, is_timeout);
    record_export_failure(signal);
}

/// Inform the shared circuit-breaker state and health counters about a
/// successful export.
fn on_export_success(signal: Signal, started: Instant) {
    _record_circuit_success_for_wrappers(signal);
    record_export_latency(signal, started.elapsed().as_secs_f64() * 1000.0);
}

// ── Core retry loop ───────────────────────────────────────────────────────────

/// The resolved outcome of a resilience evaluation.
enum ResilienceOutcome {
    Success,
    /// Circuit was open, fail_open=true — drop silently.
    FailOpenDrop,
    /// Circuit was open, fail_open=false — surface error.
    FailClosedOpen,
    /// All retries exhausted, fail_open=true — drop silently.
    FailOpenExhausted,
    /// All retries exhausted, fail_open=false — surface last error.
    FailClosedExhausted(String),
}

/// Run `make_fut` under the retry/timeout/circuit-breaker policy for `signal`.
async fn run_resilience_loop<F, Fut>(
    signal: Signal,
    policy: &ExporterPolicy,
    make_fut: F,
) -> ResilienceOutcome
where
    F: Fn() -> Fut,
    Fut: std::future::Future<Output = OTelSdkResult> + Send,
{
    let timeout = Duration::from_secs_f64(policy.timeout_seconds.max(0.0));
    // Circuit breaker is only consulted when timeout enforcement is on,
    // matching Python (resilience.py:177) and Go (resilience.go:170).
    if !timeout.is_zero() && circuit_gate(signal) {
        return if policy.fail_open {
            ResilienceOutcome::FailOpenDrop
        } else {
            ResilienceOutcome::FailClosedOpen
        };
    }

    let max_attempts = policy.retries + 1;
    let mut last_err = String::from("no attempts made");

    for attempt in 0..max_attempts {
        if attempt > 0 {
            if policy.backoff_seconds > 0.0 {
                tokio::time::sleep(Duration::from_secs_f64(policy.backoff_seconds)).await;
            }
            increment_retries(signal, 1);
        }

        let started = Instant::now();
        let (result, wrapper_timeout) = if timeout.is_zero() {
            (make_fut().await, false)
        } else {
            match tokio::time::timeout(timeout, make_fut()).await {
                Ok(inner) => (inner, false),
                Err(_) => (Err(OTelSdkError::Timeout(timeout)), true),
            }
        };

        match result {
            Ok(()) => {
                on_export_success(signal, started);
                return ResilienceOutcome::Success;
            }
            Err(err) => {
                // Treat both wrapper-imposed and SDK-reported timeouts as
                // breaker-eligible failures; everything else resets the counter.
                let is_timeout = wrapper_timeout || matches!(err, OTelSdkError::Timeout(_));
                on_export_failure(signal, is_timeout);
                last_err = format!("{err}");
            }
        }
    }

    if policy.fail_open {
        ResilienceOutcome::FailOpenExhausted
    } else {
        ResilienceOutcome::FailClosedExhausted(last_err)
    }
}

/// Convert a `ResilienceOutcome` to the `OTelSdkResult` the SDK expects.
fn outcome_to_sdk_result(outcome: ResilienceOutcome) -> OTelSdkResult {
    match outcome {
        ResilienceOutcome::Success
        | ResilienceOutcome::FailOpenDrop
        | ResilienceOutcome::FailOpenExhausted => Ok(()),
        ResilienceOutcome::FailClosedOpen => {
            Err(OTelSdkError::InternalFailure("circuit breaker open".into()))
        }
        ResilienceOutcome::FailClosedExhausted(msg) => Err(OTelSdkError::InternalFailure(msg)),
    }
}

// ── SpanExporter wrapper ──────────────────────────────────────────────────────

/// Wraps any `SpanExporter` so that every `export()` call runs under the
/// per-signal resilience policy from `resilience.rs`.
pub struct ResilientSpanExporter<E: SpanExporter> {
    inner: E,
}

impl<E: SpanExporter> ResilientSpanExporter<E> {
    pub fn new(inner: E) -> Self {
        Self { inner }
    }
}

impl<E: SpanExporter> fmt::Debug for ResilientSpanExporter<E> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ResilientSpanExporter").finish()
    }
}

impl<E: SpanExporter> SpanExporter for ResilientSpanExporter<E> {
    async fn export(&self, batch: Vec<SpanData>) -> OTelSdkResult {
        let policy = get_exporter_policy(Signal::Traces).unwrap_or_default();
        let outcome =
            run_resilience_loop(Signal::Traces, &policy, || self.inner.export(batch.clone())).await;
        outcome_to_sdk_result(outcome)
    }

    fn shutdown(&mut self) -> OTelSdkResult {
        self.inner.shutdown()
    }

    fn shutdown_with_timeout(&mut self, timeout: Duration) -> OTelSdkResult {
        self.inner.shutdown_with_timeout(timeout)
    }

    fn force_flush(&mut self) -> OTelSdkResult {
        self.inner.force_flush()
    }

    fn set_resource(&mut self, resource: &Resource) {
        self.inner.set_resource(resource)
    }
}

// ── LogExporter-specific retry loop ──────────────────────────────────────────
//
// `LogBatch<'_>` borrows its data, which prevents building a re-entrant
// `Fn() -> Fut` closure around it. Instead we reconstruct the LogBatch from
// the owned Vec on each attempt inside a specialized async function.

async fn run_log_resilience_loop<E: LogExporter>(
    signal: Signal,
    policy: &ExporterPolicy,
    owned: &[(
        opentelemetry_sdk::logs::SdkLogRecord,
        opentelemetry::InstrumentationScope,
    )],
    exporter: &E,
) -> ResilienceOutcome {
    let timeout = Duration::from_secs_f64(policy.timeout_seconds.max(0.0));
    if !timeout.is_zero() && circuit_gate(signal) {
        return if policy.fail_open {
            ResilienceOutcome::FailOpenDrop
        } else {
            ResilienceOutcome::FailClosedOpen
        };
    }

    let max_attempts = policy.retries + 1;
    let mut last_err = String::from("no attempts made");

    for attempt in 0..max_attempts {
        if attempt > 0 {
            if policy.backoff_seconds > 0.0 {
                tokio::time::sleep(Duration::from_secs_f64(policy.backoff_seconds)).await;
            }
            increment_retries(signal, 1);
        }

        let refs: Vec<(
            &opentelemetry_sdk::logs::SdkLogRecord,
            &opentelemetry::InstrumentationScope,
        )> = owned.iter().map(|(r, s)| (r, s)).collect();
        let rebatch = LogBatch::new(&refs);

        let started = Instant::now();
        let (result, wrapper_timeout) = if timeout.is_zero() {
            (exporter.export(rebatch).await, false)
        } else {
            match tokio::time::timeout(timeout, exporter.export(rebatch)).await {
                Ok(inner) => (inner, false),
                Err(_) => (Err(OTelSdkError::Timeout(timeout)), true),
            }
        };

        match result {
            Ok(()) => {
                on_export_success(signal, started);
                return ResilienceOutcome::Success;
            }
            Err(err) => {
                let is_timeout = wrapper_timeout || matches!(err, OTelSdkError::Timeout(_));
                on_export_failure(signal, is_timeout);
                last_err = format!("{err}");
            }
        }
    }

    if policy.fail_open {
        ResilienceOutcome::FailOpenExhausted
    } else {
        ResilienceOutcome::FailClosedExhausted(last_err)
    }
}

// ── LogExporter wrapper ───────────────────────────────────────────────────────

/// Wraps any `LogExporter` so that every `export()` call runs under the
/// per-signal resilience policy from `resilience.rs`.
///
/// `LogBatch<'_>` borrows its data, so the records are collected into an owned
/// `Vec` before each retry attempt.
pub struct ResilientLogExporter<E: LogExporter> {
    inner: E,
}

impl<E: LogExporter> ResilientLogExporter<E> {
    pub fn new(inner: E) -> Self {
        Self { inner }
    }
}

impl<E: LogExporter> fmt::Debug for ResilientLogExporter<E> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ResilientLogExporter").finish()
    }
}

impl<E: LogExporter> LogExporter for ResilientLogExporter<E> {
    async fn export(&self, batch: LogBatch<'_>) -> OTelSdkResult {
        // Collect into an owned Vec so retries can reconstruct the batch.
        // LogBatch<'_> borrows its data; we own the records here.
        let owned: Vec<(
            opentelemetry_sdk::logs::SdkLogRecord,
            opentelemetry::InstrumentationScope,
        )> = batch.iter().map(|(r, s)| (r.clone(), s.clone())).collect();

        let policy = get_exporter_policy(Signal::Logs).unwrap_or_default();
        // Inline retry loop — run_resilience_loop requires Fn() -> Fut, but
        // the LogBatch lifetime prevents building a re-borrows in a closure.
        let outcome = run_log_resilience_loop(Signal::Logs, &policy, &owned, &self.inner).await;
        outcome_to_sdk_result(outcome)
    }

    fn shutdown(&self) -> OTelSdkResult {
        self.inner.shutdown()
    }

    fn shutdown_with_timeout(&self, timeout: Duration) -> OTelSdkResult {
        self.inner.shutdown_with_timeout(timeout)
    }

    fn set_resource(&mut self, resource: &Resource) {
        self.inner.set_resource(resource)
    }
}

// ── PushMetricExporter wrapper ────────────────────────────────────────────────

/// Wraps any `PushMetricExporter` so that every `export()` call runs under the
/// per-signal resilience policy from `resilience.rs`.
///
/// `ResourceMetrics` is not `Clone`; retries re-export the same reference
/// (the SDK guarantees `export()` is never called concurrently).
pub struct ResilientMetricExporter<E: PushMetricExporter> {
    inner: E,
}

impl<E: PushMetricExporter> ResilientMetricExporter<E> {
    pub fn new(inner: E) -> Self {
        Self { inner }
    }
}

impl<E: PushMetricExporter> fmt::Debug for ResilientMetricExporter<E> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ResilientMetricExporter").finish()
    }
}

impl<E: PushMetricExporter> PushMetricExporter for ResilientMetricExporter<E> {
    async fn export(&self, metrics: &ResourceMetrics) -> OTelSdkResult {
        let policy = get_exporter_policy(Signal::Metrics).unwrap_or_default();
        let outcome =
            run_resilience_loop(Signal::Metrics, &policy, || self.inner.export(metrics)).await;
        outcome_to_sdk_result(outcome)
    }

    fn force_flush(&self) -> OTelSdkResult {
        self.inner.force_flush()
    }

    fn shutdown_with_timeout(&self, timeout: Duration) -> OTelSdkResult {
        self.inner.shutdown_with_timeout(timeout)
    }

    fn shutdown(&self) -> OTelSdkResult {
        self.inner.shutdown()
    }

    fn temporality(&self) -> Temporality {
        self.inner.temporality()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::resilience::{_reset_resilience_for_tests, set_exporter_policy};
    use crate::testing::acquire_test_state_lock;
    use opentelemetry::InstrumentationScope;
    use opentelemetry_sdk::logs::SdkLogRecord;
    use std::sync::atomic::{AtomicU32, Ordering};
    use std::sync::Arc;

    fn rt() -> tokio::runtime::Runtime {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("runtime")
    }

    // ── Stub exporters ────────────────────────────────────────────────────────

    #[derive(Debug, Clone)]
    struct StubSpanExporter {
        calls: Arc<AtomicU32>,
        fail_first_n: u32,
        fail_as_timeout: bool,
    }

    impl StubSpanExporter {
        fn new_always_ok() -> Self {
            Self {
                calls: Arc::new(AtomicU32::new(0)),
                fail_first_n: 0,
                fail_as_timeout: false,
            }
        }

        fn new_fail_first(n: u32) -> Self {
            Self {
                calls: Arc::new(AtomicU32::new(0)),
                fail_first_n: n,
                fail_as_timeout: false,
            }
        }

        fn new_always_fail() -> Self {
            Self {
                calls: Arc::new(AtomicU32::new(0)),
                fail_first_n: u32::MAX,
                fail_as_timeout: false,
            }
        }

        fn new_always_timeout() -> Self {
            Self {
                calls: Arc::new(AtomicU32::new(0)),
                fail_first_n: u32::MAX,
                fail_as_timeout: true,
            }
        }
    }

    impl SpanExporter for StubSpanExporter {
        async fn export(&self, _batch: Vec<SpanData>) -> OTelSdkResult {
            let n = self.calls.fetch_add(1, Ordering::SeqCst);
            if n < self.fail_first_n {
                if self.fail_as_timeout {
                    Err(OTelSdkError::Timeout(Duration::from_secs(1)))
                } else {
                    Err(OTelSdkError::InternalFailure("stub failure".into()))
                }
            } else {
                Ok(())
            }
        }
    }

    #[derive(Debug, Clone)]
    struct StubLogExporter {
        calls: Arc<AtomicU32>,
        fail_first_n: u32,
        fail_as_timeout: bool,
    }

    impl StubLogExporter {
        fn new_always_ok() -> Self {
            Self {
                calls: Arc::new(AtomicU32::new(0)),
                fail_first_n: 0,
                fail_as_timeout: false,
            }
        }

        fn new_fail_first(n: u32) -> Self {
            Self {
                calls: Arc::new(AtomicU32::new(0)),
                fail_first_n: n,
                fail_as_timeout: false,
            }
        }

        fn new_always_fail() -> Self {
            Self {
                calls: Arc::new(AtomicU32::new(0)),
                fail_first_n: u32::MAX,
                fail_as_timeout: false,
            }
        }

        fn new_always_timeout() -> Self {
            Self {
                calls: Arc::new(AtomicU32::new(0)),
                fail_first_n: u32::MAX,
                fail_as_timeout: true,
            }
        }
    }

    impl LogExporter for StubLogExporter {
        async fn export(&self, _batch: LogBatch<'_>) -> OTelSdkResult {
            let n = self.calls.fetch_add(1, Ordering::SeqCst);
            if n < self.fail_first_n {
                if self.fail_as_timeout {
                    Err(OTelSdkError::Timeout(Duration::from_secs(1)))
                } else {
                    Err(OTelSdkError::InternalFailure("stub failure".into()))
                }
            } else {
                Ok(())
            }
        }
    }

    #[derive(Debug)]
    struct StubMetricExporter {
        calls: Arc<AtomicU32>,
        fail_first_n: u32,
        fail_as_timeout: bool,
    }

    impl StubMetricExporter {
        fn new_always_ok() -> Self {
            Self {
                calls: Arc::new(AtomicU32::new(0)),
                fail_first_n: 0,
                fail_as_timeout: false,
            }
        }

        fn new_fail_first(n: u32) -> Self {
            Self {
                calls: Arc::new(AtomicU32::new(0)),
                fail_first_n: n,
                fail_as_timeout: false,
            }
        }

        fn new_always_fail() -> Self {
            Self {
                calls: Arc::new(AtomicU32::new(0)),
                fail_first_n: u32::MAX,
                fail_as_timeout: false,
            }
        }

        fn new_always_timeout() -> Self {
            Self {
                calls: Arc::new(AtomicU32::new(0)),
                fail_first_n: u32::MAX,
                fail_as_timeout: true,
            }
        }
    }

    impl PushMetricExporter for StubMetricExporter {
        async fn export(&self, _metrics: &ResourceMetrics) -> OTelSdkResult {
            let n = self.calls.fetch_add(1, Ordering::SeqCst);
            if n < self.fail_first_n {
                if self.fail_as_timeout {
                    Err(OTelSdkError::Timeout(Duration::from_secs(1)))
                } else {
                    Err(OTelSdkError::InternalFailure("stub failure".into()))
                }
            } else {
                Ok(())
            }
        }

        fn force_flush(&self) -> OTelSdkResult {
            Ok(())
        }
        fn shutdown_with_timeout(&self, _t: Duration) -> OTelSdkResult {
            Ok(())
        }
        fn temporality(&self) -> Temporality {
            Temporality::Cumulative
        }
    }

    fn empty_log_batch_data() -> Vec<(SdkLogRecord, InstrumentationScope)> {
        vec![]
    }

    fn empty_resource_metrics() -> ResourceMetrics {
        ResourceMetrics::default()
    }

    // ── SpanExporter tests ────────────────────────────────────────────────────

    #[test]
    fn span_exporter_success_passthrough() {
        let _g = acquire_test_state_lock();
        _reset_resilience_for_tests();
        let stub = StubSpanExporter::new_always_ok();
        let calls = stub.calls.clone();
        let w = ResilientSpanExporter::new(stub);
        rt().block_on(async move {
            w.export(vec![]).await.expect("must succeed");
        });
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn span_exporter_fail_open_drop_returns_ok() {
        let _g = acquire_test_state_lock();
        _reset_resilience_for_tests();
        set_exporter_policy(
            Signal::Traces,
            ExporterPolicy {
                retries: 0,
                fail_open: true,
                ..ExporterPolicy::default()
            },
        )
        .unwrap();
        let stub = StubSpanExporter::new_fail_first(1);
        let calls = stub.calls.clone();
        let w = ResilientSpanExporter::new(stub);
        // fail_open=true: error is absorbed, Ok returned
        rt().block_on(async move {
            w.export(vec![]).await.expect("fail-open must return Ok");
        });
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn span_exporter_fail_closed_surfaces_error() {
        let _g = acquire_test_state_lock();
        _reset_resilience_for_tests();
        set_exporter_policy(
            Signal::Traces,
            ExporterPolicy {
                retries: 0,
                fail_open: false,
                ..ExporterPolicy::default()
            },
        )
        .unwrap();
        let stub = StubSpanExporter::new_fail_first(1);
        let w = ResilientSpanExporter::new(stub);
        rt().block_on(async move {
            w.export(vec![])
                .await
                .expect_err("fail-closed must return Err");
        });
    }

    #[test]
    fn span_exporter_retries_invoke_inner_n_times() {
        let _g = acquire_test_state_lock();
        _reset_resilience_for_tests();
        set_exporter_policy(
            Signal::Traces,
            ExporterPolicy {
                retries: 2,
                backoff_seconds: 0.0,
                timeout_seconds: 0.0,
                fail_open: true,
                ..ExporterPolicy::default()
            },
        )
        .unwrap();
        // Fails on attempts 0 and 1, succeeds on attempt 2 (index 2 >= fail_first_n=2).
        let stub = StubSpanExporter::new_fail_first(2);
        let calls = stub.calls.clone();
        let w = ResilientSpanExporter::new(stub);
        rt().block_on(async move {
            w.export(vec![]).await.expect("must succeed after retry");
        });
        assert_eq!(calls.load(Ordering::SeqCst), 3);
    }

    #[test]
    fn span_exporter_circuit_breaker_trips_after_threshold_failures() {
        let _g = acquire_test_state_lock();
        _reset_resilience_for_tests();
        set_exporter_policy(
            Signal::Traces,
            ExporterPolicy {
                retries: 0,
                backoff_seconds: 0.0,
                // Non-zero timeout so the circuit gate is consulted, and
                // the stub returns Timeout errors so the breaker counts them.
                timeout_seconds: 1.0,
                fail_open: true,
                ..ExporterPolicy::default()
            },
        )
        .unwrap();
        let stub = StubSpanExporter::new_always_timeout();
        let calls = stub.calls.clone();
        let w = ResilientSpanExporter::new(stub);
        rt().block_on(async {
            // Trip the circuit: 3 failures required.
            for _ in 0..3 {
                w.export(vec![]).await.ok();
            }
            assert_eq!(calls.load(Ordering::SeqCst), 3);
            // Circuit is now open — inner must NOT be invoked.
            w.export(vec![])
                .await
                .expect("fail-open circuit must return Ok");
            assert_eq!(
                calls.load(Ordering::SeqCst),
                3,
                "circuit open: inner must not be called"
            );
        });
    }

    #[test]
    fn span_exporter_circuit_breaker_fail_closed_returns_error() {
        let _g = acquire_test_state_lock();
        _reset_resilience_for_tests();
        set_exporter_policy(
            Signal::Traces,
            ExporterPolicy {
                retries: 0,
                backoff_seconds: 0.0,
                timeout_seconds: 1.0,
                fail_open: false,
                ..ExporterPolicy::default()
            },
        )
        .unwrap();
        let stub = StubSpanExporter::new_always_timeout();
        let calls = stub.calls.clone();
        let w = ResilientSpanExporter::new(stub);
        rt().block_on(async {
            for _ in 0..3 {
                w.export(vec![]).await.expect_err("fail-closed must error");
            }
            assert_eq!(calls.load(Ordering::SeqCst), 3);
            // Circuit open, fail-closed: next call must return Err without calling inner.
            w.export(vec![])
                .await
                .expect_err("fail-closed circuit must return Err");
            assert_eq!(
                calls.load(Ordering::SeqCst),
                3,
                "circuit open: inner must not be called"
            );
        });
    }

    #[test]
    fn span_exporter_shutdown_and_force_flush_forwarded() {
        let _g = acquire_test_state_lock();
        _reset_resilience_for_tests();
        let stub = StubSpanExporter::new_always_ok();
        let mut w = ResilientSpanExporter::new(stub);
        w.force_flush().expect("force_flush must succeed");
        w.shutdown().expect("shutdown must succeed");
    }

    // ── LogExporter tests ─────────────────────────────────────────────────────

    #[test]
    fn log_exporter_success_passthrough() {
        let _g = acquire_test_state_lock();
        _reset_resilience_for_tests();
        let stub = StubLogExporter::new_always_ok();
        let calls = stub.calls.clone();
        let w = ResilientLogExporter::new(stub);
        let data = empty_log_batch_data();
        let refs: Vec<_> = data.iter().map(|(r, s)| (r, s)).collect();
        let batch = LogBatch::new(&refs);
        rt().block_on(async move {
            w.export(batch).await.expect("must succeed");
        });
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn log_exporter_fail_open_drop_returns_ok() {
        let _g = acquire_test_state_lock();
        _reset_resilience_for_tests();
        set_exporter_policy(
            Signal::Logs,
            ExporterPolicy {
                retries: 0,
                fail_open: true,
                ..ExporterPolicy::default()
            },
        )
        .unwrap();
        let stub = StubLogExporter::new_fail_first(1);
        let calls = stub.calls.clone();
        let w = ResilientLogExporter::new(stub);
        let data = empty_log_batch_data();
        let refs: Vec<_> = data.iter().map(|(r, s)| (r, s)).collect();
        let batch = LogBatch::new(&refs);
        rt().block_on(async move {
            w.export(batch).await.expect("fail-open must return Ok");
        });
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn log_exporter_fail_closed_surfaces_error() {
        let _g = acquire_test_state_lock();
        _reset_resilience_for_tests();
        set_exporter_policy(
            Signal::Logs,
            ExporterPolicy {
                retries: 0,
                fail_open: false,
                ..ExporterPolicy::default()
            },
        )
        .unwrap();
        let stub = StubLogExporter::new_fail_first(1);
        let w = ResilientLogExporter::new(stub);
        let data = empty_log_batch_data();
        let refs: Vec<_> = data.iter().map(|(r, s)| (r, s)).collect();
        let batch = LogBatch::new(&refs);
        rt().block_on(async move {
            w.export(batch)
                .await
                .expect_err("fail-closed must return Err");
        });
    }

    #[test]
    fn log_exporter_retries_invoke_inner_n_times() {
        let _g = acquire_test_state_lock();
        _reset_resilience_for_tests();
        set_exporter_policy(
            Signal::Logs,
            ExporterPolicy {
                retries: 2,
                backoff_seconds: 0.0,
                timeout_seconds: 0.0,
                fail_open: true,
                ..ExporterPolicy::default()
            },
        )
        .unwrap();
        let stub = StubLogExporter::new_fail_first(2);
        let calls = stub.calls.clone();
        let w = ResilientLogExporter::new(stub);
        let data = empty_log_batch_data();
        let refs: Vec<_> = data.iter().map(|(r, s)| (r, s)).collect();
        let batch = LogBatch::new(&refs);
        rt().block_on(async move {
            w.export(batch).await.expect("must succeed after retry");
        });
        assert_eq!(calls.load(Ordering::SeqCst), 3);
    }

    #[test]
    fn log_exporter_circuit_breaker_trips_after_threshold_failures() {
        let _g = acquire_test_state_lock();
        _reset_resilience_for_tests();
        set_exporter_policy(
            Signal::Logs,
            ExporterPolicy {
                retries: 0,
                backoff_seconds: 0.0,
                timeout_seconds: 1.0,
                fail_open: true,
                ..ExporterPolicy::default()
            },
        )
        .unwrap();
        let stub = StubLogExporter::new_always_timeout();
        let calls = stub.calls.clone();
        let w = ResilientLogExporter::new(stub);
        let data = empty_log_batch_data();
        rt().block_on(async {
            for _ in 0..3 {
                let refs: Vec<_> = data.iter().map(|(r, s)| (r, s)).collect();
                let batch = LogBatch::new(&refs);
                w.export(batch).await.ok();
            }
            assert_eq!(calls.load(Ordering::SeqCst), 3);
            let refs: Vec<_> = data.iter().map(|(r, s)| (r, s)).collect();
            let batch = LogBatch::new(&refs);
            w.export(batch)
                .await
                .expect("fail-open circuit must return Ok");
            assert_eq!(
                calls.load(Ordering::SeqCst),
                3,
                "circuit open: inner must not be called"
            );
        });
    }

    #[test]
    fn log_exporter_shutdown_forwarded() {
        let _g = acquire_test_state_lock();
        _reset_resilience_for_tests();
        let stub = StubLogExporter::new_always_ok();
        let w = ResilientLogExporter::new(stub);
        w.shutdown().expect("shutdown must succeed");
    }

    // ── PushMetricExporter tests ──────────────────────────────────────────────

    #[test]
    fn metric_exporter_success_passthrough() {
        let _g = acquire_test_state_lock();
        _reset_resilience_for_tests();
        let stub = StubMetricExporter::new_always_ok();
        let calls = stub.calls.clone();
        let w = ResilientMetricExporter::new(stub);
        let rm = empty_resource_metrics();
        rt().block_on(async move {
            w.export(&rm).await.expect("must succeed");
        });
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn metric_exporter_fail_open_drop_returns_ok() {
        let _g = acquire_test_state_lock();
        _reset_resilience_for_tests();
        set_exporter_policy(
            Signal::Metrics,
            ExporterPolicy {
                retries: 0,
                fail_open: true,
                ..ExporterPolicy::default()
            },
        )
        .unwrap();
        let stub = StubMetricExporter::new_fail_first(1);
        let calls = stub.calls.clone();
        let w = ResilientMetricExporter::new(stub);
        let rm = empty_resource_metrics();
        rt().block_on(async move {
            w.export(&rm).await.expect("fail-open must return Ok");
        });
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn metric_exporter_fail_closed_surfaces_error() {
        let _g = acquire_test_state_lock();
        _reset_resilience_for_tests();
        set_exporter_policy(
            Signal::Metrics,
            ExporterPolicy {
                retries: 0,
                fail_open: false,
                ..ExporterPolicy::default()
            },
        )
        .unwrap();
        let stub = StubMetricExporter::new_fail_first(1);
        let w = ResilientMetricExporter::new(stub);
        let rm = empty_resource_metrics();
        rt().block_on(async move {
            w.export(&rm)
                .await
                .expect_err("fail-closed must return Err");
        });
    }

    #[test]
    fn metric_exporter_retries_invoke_inner_n_times() {
        let _g = acquire_test_state_lock();
        _reset_resilience_for_tests();
        set_exporter_policy(
            Signal::Metrics,
            ExporterPolicy {
                retries: 2,
                backoff_seconds: 0.0,
                timeout_seconds: 0.0,
                fail_open: true,
                ..ExporterPolicy::default()
            },
        )
        .unwrap();
        let stub = StubMetricExporter::new_fail_first(2);
        let calls = stub.calls.clone();
        let w = ResilientMetricExporter::new(stub);
        let rm = empty_resource_metrics();
        rt().block_on(async move {
            w.export(&rm).await.expect("must succeed after retry");
        });
        assert_eq!(calls.load(Ordering::SeqCst), 3);
    }

    #[test]
    fn metric_exporter_circuit_breaker_trips_after_threshold_failures() {
        let _g = acquire_test_state_lock();
        _reset_resilience_for_tests();
        set_exporter_policy(
            Signal::Metrics,
            ExporterPolicy {
                retries: 0,
                backoff_seconds: 0.0,
                timeout_seconds: 1.0,
                fail_open: true,
                ..ExporterPolicy::default()
            },
        )
        .unwrap();
        let stub = StubMetricExporter::new_always_timeout();
        let calls = stub.calls.clone();
        let w = ResilientMetricExporter::new(stub);
        let rm = empty_resource_metrics();
        rt().block_on(async {
            for _ in 0..3 {
                w.export(&rm).await.ok();
            }
            assert_eq!(calls.load(Ordering::SeqCst), 3);
            w.export(&rm)
                .await
                .expect("fail-open circuit must return Ok");
            assert_eq!(
                calls.load(Ordering::SeqCst),
                3,
                "circuit open: inner must not be called"
            );
        });
    }

    #[test]
    fn metric_exporter_force_flush_and_shutdown_forwarded() {
        let _g = acquire_test_state_lock();
        _reset_resilience_for_tests();
        let stub = StubMetricExporter::new_always_ok();
        let w = ResilientMetricExporter::new(stub);
        w.force_flush().expect("force_flush must succeed");
        w.shutdown().expect("shutdown must succeed");
    }

    #[test]
    fn metric_exporter_temporality_forwarded() {
        let _g = acquire_test_state_lock();
        _reset_resilience_for_tests();
        let stub = StubMetricExporter::new_always_ok();
        let w = ResilientMetricExporter::new(stub);
        assert_eq!(w.temporality(), Temporality::Cumulative);
    }
}
