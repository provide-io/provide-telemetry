// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

//! Stub exporters and SpanExporter wrapper tests for `otel/resilient.rs`.
//! Mounted via `#[path]` so this file lives beside `resilient.rs` without
//! pushing it past the 500-LOC ceiling. The log and metric wrapper tests
//! live in `resilient_log_metric_tests.rs`.

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
