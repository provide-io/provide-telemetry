// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

//! Health-counter integration tests for the resilient OTel exporters.
//!
//! The behavioral wrapper tests in `resilient_span_tests.rs` and
//! `resilient_log_metric_tests.rs` cover what each export call returns
//! (Ok / Err / circuit-open). The previous suite didn't pin the *side
//! effect* on the global health snapshot — runtime export failures were
//! exercised, but no test asserted that `export_failures_{logs,traces,
//! metrics}` and `retries_{logs,traces,metrics}` actually incremented.
//! Without that pin a future refactor of the resilience loop could
//! silently stop counting failures and the wrapper tests would still
//! pass. Mounted via `#[path]` from `otel/resilient.rs`.

#![allow(dead_code)]
#![cfg(test)]

use super::*;
use crate::health::{_reset_health_for_tests, get_health_snapshot};
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

#[derive(Debug, Clone)]
struct AlwaysFailSpan(Arc<AtomicU32>);
impl SpanExporter for AlwaysFailSpan {
    async fn export(&self, _batch: Vec<SpanData>) -> OTelSdkResult {
        self.0.fetch_add(1, Ordering::SeqCst);
        Err(OTelSdkError::InternalFailure("stub failure".into()))
    }
}

#[derive(Debug, Clone)]
struct AlwaysFailLog(Arc<AtomicU32>);
impl LogExporter for AlwaysFailLog {
    async fn export(&self, _batch: LogBatch<'_>) -> OTelSdkResult {
        self.0.fetch_add(1, Ordering::SeqCst);
        Err(OTelSdkError::InternalFailure("stub failure".into()))
    }
}

#[derive(Debug)]
struct AlwaysFailMetric(Arc<AtomicU32>);
impl PushMetricExporter for AlwaysFailMetric {
    async fn export(&self, _metrics: &ResourceMetrics) -> OTelSdkResult {
        self.0.fetch_add(1, Ordering::SeqCst);
        Err(OTelSdkError::InternalFailure("stub failure".into()))
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

fn fail_open_zero_retry(signal: Signal) {
    set_exporter_policy(
        signal,
        ExporterPolicy {
            retries: 0,
            backoff_seconds: 0.0,
            timeout_seconds: 0.0,
            fail_open: true,
            ..ExporterPolicy::default()
        },
    )
    .unwrap();
}

fn fail_open_two_retries(signal: Signal) {
    set_exporter_policy(
        signal,
        ExporterPolicy {
            retries: 2,
            backoff_seconds: 0.0,
            timeout_seconds: 0.0,
            fail_open: true,
            ..ExporterPolicy::default()
        },
    )
    .unwrap();
}

#[test]
fn span_runtime_failure_increments_export_failures_counter() {
    let _g = acquire_test_state_lock();
    _reset_resilience_for_tests();
    _reset_health_for_tests();
    fail_open_zero_retry(Signal::Traces);
    let calls = Arc::new(AtomicU32::new(0));
    let w = ResilientSpanExporter::new(AlwaysFailSpan(calls.clone()));
    rt().block_on(async move {
        w.export(vec![]).await.expect("fail-open returns Ok");
    });
    let snap = get_health_snapshot();
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(snap.export_failures_traces, 1);
    assert_eq!(snap.export_failures_logs, 0);
    assert_eq!(snap.export_failures_metrics, 0);
}

#[test]
fn log_runtime_failure_increments_export_failures_counter() {
    let _g = acquire_test_state_lock();
    _reset_resilience_for_tests();
    _reset_health_for_tests();
    fail_open_zero_retry(Signal::Logs);
    let calls = Arc::new(AtomicU32::new(0));
    let w = ResilientLogExporter::new(AlwaysFailLog(calls.clone()));
    let data: Vec<(SdkLogRecord, InstrumentationScope)> = vec![];
    let refs: Vec<_> = data.iter().map(|(r, s)| (r, s)).collect();
    let batch = LogBatch::new(&refs);
    rt().block_on(async move {
        w.export(batch).await.expect("fail-open returns Ok");
    });
    let snap = get_health_snapshot();
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(snap.export_failures_logs, 1);
    assert_eq!(snap.export_failures_traces, 0);
    assert_eq!(snap.export_failures_metrics, 0);
}

#[test]
fn metric_runtime_failure_increments_export_failures_counter() {
    let _g = acquire_test_state_lock();
    _reset_resilience_for_tests();
    _reset_health_for_tests();
    fail_open_zero_retry(Signal::Metrics);
    let calls = Arc::new(AtomicU32::new(0));
    let w = ResilientMetricExporter::new(AlwaysFailMetric(calls.clone()));
    let rm = ResourceMetrics::default();
    rt().block_on(async move {
        w.export(&rm).await.expect("fail-open returns Ok");
    });
    let snap = get_health_snapshot();
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(snap.export_failures_metrics, 1);
    assert_eq!(snap.export_failures_logs, 0);
    assert_eq!(snap.export_failures_traces, 0);
}

#[test]
fn span_retries_increment_retry_counter_per_attempt_after_first() {
    let _g = acquire_test_state_lock();
    _reset_resilience_for_tests();
    _reset_health_for_tests();
    fail_open_two_retries(Signal::Traces);
    let calls = Arc::new(AtomicU32::new(0));
    let w = ResilientSpanExporter::new(AlwaysFailSpan(calls.clone()));
    rt().block_on(async move {
        w.export(vec![]).await.expect("fail-open returns Ok");
    });
    let snap = get_health_snapshot();
    // 1 initial attempt + 2 retries = 3 stub calls; retries counter ticks
    // only on attempts after the first, so it must be exactly 2.
    assert_eq!(calls.load(Ordering::SeqCst), 3);
    assert_eq!(snap.retries_traces, 2);
    assert_eq!(snap.export_failures_traces, 3);
    assert_eq!(snap.retries_logs, 0);
    assert_eq!(snap.retries_metrics, 0);
}

#[test]
fn log_retries_increment_retry_counter_per_attempt_after_first() {
    let _g = acquire_test_state_lock();
    _reset_resilience_for_tests();
    _reset_health_for_tests();
    fail_open_two_retries(Signal::Logs);
    let calls = Arc::new(AtomicU32::new(0));
    let w = ResilientLogExporter::new(AlwaysFailLog(calls.clone()));
    let data: Vec<(SdkLogRecord, InstrumentationScope)> = vec![];
    let refs: Vec<_> = data.iter().map(|(r, s)| (r, s)).collect();
    let batch = LogBatch::new(&refs);
    rt().block_on(async move {
        w.export(batch).await.expect("fail-open returns Ok");
    });
    let snap = get_health_snapshot();
    assert_eq!(calls.load(Ordering::SeqCst), 3);
    assert_eq!(snap.retries_logs, 2);
    assert_eq!(snap.export_failures_logs, 3);
}
