// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Per-export resilience wrappers for OTel SDK exporters.
//!
//! ## Why a separate file
//!
//! The generic [`crate::resilience::run_with_resilience`] is hard-typed to
//! `Result<T, TelemetryError>` for backwards compatibility with downstream
//! callers. The OTel SDK exporter traits return [`OTelSdkResult`]
//! (`Result<(), OTelSdkError>`) instead, so this module exists only to
//! adapt the SDK trait signatures. The retry/timeout/backoff/circuit-breaker
//! body itself lives in [`crate::resilience::run_with_resilience_inner`] and
//! is shared between both callsites — there is exactly one loop body, so
//! semantics cannot drift.
//!
//! All three OTel exporter wrappers (Span, Metric, Log) delegate to the same
//! inner primitive even though `LogBatch<'_>` borrows its data: the Log
//! wrapper rebuilds the batch inside an async-block closure per attempt, so
//! the future state machine owns the `refs` slice for the duration of each
//! `export()` call.
//!
//! The wrapper reads `ExporterPolicy` and circuit state on every `export()`
//! call, so hot-reloaded policies take effect immediately — the same guarantee
//! as `run_with_resilience`.

use std::fmt;
use std::time::Duration;

use opentelemetry_sdk::error::{OTelSdkError, OTelSdkResult};
use opentelemetry_sdk::logs::{LogBatch, LogExporter};
use opentelemetry_sdk::metrics::data::ResourceMetrics;
use opentelemetry_sdk::metrics::exporter::PushMetricExporter;
use opentelemetry_sdk::metrics::Temporality;
use opentelemetry_sdk::trace::{SpanData, SpanExporter};
use opentelemetry_sdk::Resource;

use crate::resilience::{get_exporter_policy, run_with_resilience_inner, ExporterPolicy};
use crate::sampling::Signal;

// ── Adapter from the generic primitive to OTelSdkResult ──────────────────────

/// Run `make_fut` under the per-signal resilience policy and translate the
/// generic result into `OTelSdkResult`. `Ok(_)` (success or fail-open drop)
/// becomes `Ok(())`; `Err(e)` surfaces the exporter's own variant unchanged
/// (preserving `Timeout(_)` distinct from `InternalFailure(_)`).
async fn run_otel_resilience<F, Fut>(
    signal: Signal,
    policy: &ExporterPolicy,
    make_fut: F,
) -> OTelSdkResult
where
    F: Fn() -> Fut,
    Fut: std::future::Future<Output = OTelSdkResult> + Send,
{
    match run_with_resilience_inner(
        signal,
        policy,
        make_fut,
        OTelSdkError::Timeout,
        |e| matches!(e, OTelSdkError::Timeout(_)),
        || OTelSdkError::InternalFailure("circuit breaker open".into()),
    )
    .await
    {
        Ok(_) => Ok(()),
        Err(e) => Err(e),
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
        run_otel_resilience(Signal::Traces, &policy, || self.inner.export(batch.clone())).await
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
        // Reconstruct the borrowed LogBatch inside an async block per attempt —
        // the future state machine owns `refs` for the duration of `export()`,
        // so the closure satisfies `Fn() -> Fut` despite the borrowed batch.
        run_otel_resilience(Signal::Logs, &policy, || async {
            let refs: Vec<(
                &opentelemetry_sdk::logs::SdkLogRecord,
                &opentelemetry::InstrumentationScope,
            )> = owned.iter().map(|(r, s)| (r, s)).collect();
            let rebatch = LogBatch::new(&refs);
            self.inner.export(rebatch).await
        })
        .await
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
        run_otel_resilience(Signal::Metrics, &policy, || self.inner.export(metrics)).await
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

#[cfg(test)]
#[path = "resilient_health_tests.rs"]
mod health_tests;

#[cfg(test)]
#[path = "resilient_forwarding_tests.rs"]
mod forwarding_tests;
