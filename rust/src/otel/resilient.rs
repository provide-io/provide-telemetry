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
#[path = "resilient_span_tests.rs"]
mod span_tests;

#[cfg(test)]
#[path = "resilient_log_metric_tests.rs"]
mod log_metric_tests;
