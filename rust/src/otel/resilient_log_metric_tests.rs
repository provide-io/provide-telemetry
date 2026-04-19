// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

//! LogExporter and PushMetricExporter wrapper tests for `otel/resilient.rs`.
//! Stubs and span-exporter tests live in `resilient_span_tests.rs`. Both
//! files are mounted via `#[path]` from `resilient.rs`.
//!
//! Stubs are redeclared inline (rather than imported from the span-tests
//! file) because Rust's per-file `#[cfg(test)]` modules don't have a clean
//! cross-file sharing story without converting the whole module to a
//! directory. The duplication is small and bounded.

#![allow(dead_code)]
#![cfg(test)]

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

// ── Variant preservation through run_otel_resilience ─────────────────────
// Pins the behavioral contract introduced by the resilience-loop unification:
// when an SDK exporter returns OTelSdkError::Timeout(_), the wrapper must
// surface it as Timeout(_) — NOT flatten to InternalFailure(format!("{e}")).
// Distinct timeout vs internal-failure variants matter for downstream OTel
// SDK consumers that branch on the error kind.

#[test]
fn log_exporter_preserves_timeout_variant_through_wrapper() {
    let _g = acquire_test_state_lock();
    _reset_resilience_for_tests();
    set_exporter_policy(
        Signal::Logs,
        ExporterPolicy {
            retries: 0,
            fail_open: false,
            timeout_seconds: 0.0, // disable wrapper timeout — SDK error is the only source
            ..ExporterPolicy::default()
        },
    )
    .unwrap();
    let stub = StubLogExporter::new_always_timeout();
    let w = ResilientLogExporter::new(stub);
    let data = empty_log_batch_data();
    let refs: Vec<_> = data.iter().map(|(r, s)| (r, s)).collect();
    let batch = LogBatch::new(&refs);
    rt().block_on(async move {
        let err = w
            .export(batch)
            .await
            .expect_err("fail-closed must surface SDK error");
        assert!(
            matches!(err, OTelSdkError::Timeout(_)),
            "wrapper must preserve OTelSdkError::Timeout variant, got: {err:?}"
        );
    });
}
