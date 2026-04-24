// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#![cfg(test)]

use super::*;
use crate::testing::acquire_test_state_lock;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

#[derive(Debug)]
struct ForwardingSpanExporter {
    shutdown_with_timeout_called: Arc<AtomicBool>,
}

impl SpanExporter for ForwardingSpanExporter {
    async fn export(&self, _batch: Vec<SpanData>) -> OTelSdkResult {
        Ok(())
    }

    fn shutdown_with_timeout(&mut self, _timeout: Duration) -> OTelSdkResult {
        self.shutdown_with_timeout_called
            .store(true, Ordering::SeqCst);
        Ok(())
    }
}

#[derive(Debug)]
struct ForwardingLogExporter {
    shutdown_with_timeout_called: Arc<AtomicBool>,
}

impl LogExporter for ForwardingLogExporter {
    async fn export(&self, _batch: LogBatch<'_>) -> OTelSdkResult {
        Ok(())
    }

    fn shutdown_with_timeout(&self, _timeout: Duration) -> OTelSdkResult {
        self.shutdown_with_timeout_called
            .store(true, Ordering::SeqCst);
        Ok(())
    }
}

#[derive(Debug)]
struct ForwardingMetricExporter {
    shutdown_with_timeout_called: Arc<AtomicBool>,
}

impl PushMetricExporter for ForwardingMetricExporter {
    async fn export(&self, _metrics: &ResourceMetrics) -> OTelSdkResult {
        Ok(())
    }

    fn force_flush(&self) -> OTelSdkResult {
        Ok(())
    }

    fn shutdown_with_timeout(&self, _timeout: Duration) -> OTelSdkResult {
        self.shutdown_with_timeout_called
            .store(true, Ordering::SeqCst);
        Ok(())
    }

    fn temporality(&self) -> Temporality {
        Temporality::Cumulative
    }
}

#[test]
fn resilient_exporter_debug_impls_report_stable_type_names() {
    let _guard = acquire_test_state_lock();

    let span = ResilientSpanExporter::new(ForwardingSpanExporter {
        shutdown_with_timeout_called: Arc::new(AtomicBool::new(false)),
    });
    let logs = ResilientLogExporter::new(ForwardingLogExporter {
        shutdown_with_timeout_called: Arc::new(AtomicBool::new(false)),
    });
    let metrics = ResilientMetricExporter::new(ForwardingMetricExporter {
        shutdown_with_timeout_called: Arc::new(AtomicBool::new(false)),
    });

    assert_eq!(format!("{span:?}"), "ResilientSpanExporter");
    assert_eq!(format!("{logs:?}"), "ResilientLogExporter");
    assert_eq!(format!("{metrics:?}"), "ResilientMetricExporter");
}

#[test]
fn resilient_exporter_shutdown_with_timeout_forwards_to_inner_exporter() {
    let _guard = acquire_test_state_lock();

    let span_called = Arc::new(AtomicBool::new(false));
    let mut span = ResilientSpanExporter::new(ForwardingSpanExporter {
        shutdown_with_timeout_called: span_called.clone(),
    });
    span.shutdown_with_timeout(Duration::from_millis(1))
        .expect("span shutdown should succeed");
    assert!(span_called.load(Ordering::SeqCst));

    let log_called = Arc::new(AtomicBool::new(false));
    let log = ResilientLogExporter::new(ForwardingLogExporter {
        shutdown_with_timeout_called: log_called.clone(),
    });
    log.shutdown_with_timeout(Duration::from_millis(1))
        .expect("log shutdown should succeed");
    assert!(log_called.load(Ordering::SeqCst));

    let metric_called = Arc::new(AtomicBool::new(false));
    let metric = ResilientMetricExporter::new(ForwardingMetricExporter {
        shutdown_with_timeout_called: metric_called.clone(),
    });
    metric
        .shutdown_with_timeout(Duration::from_millis(1))
        .expect("metric shutdown should succeed");
    assert!(metric_called.load(Ordering::SeqCst));
}
