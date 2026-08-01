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
    resource_set: Arc<AtomicBool>,
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

    fn set_resource(&mut self, _resource: &Resource) {
        self.resource_set.store(true, Ordering::SeqCst);
    }
}

#[derive(Debug)]
struct ForwardingLogExporter {
    shutdown_with_timeout_called: Arc<AtomicBool>,
    resource_set: Arc<AtomicBool>,
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

    fn set_resource(&mut self, _resource: &Resource) {
        self.resource_set.store(true, Ordering::SeqCst);
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
        Temporality::Delta
    }
}

#[test]
fn resilient_exporter_debug_impls_report_stable_type_names() {
    let _guard = acquire_test_state_lock();

    let span = ResilientSpanExporter::new(ForwardingSpanExporter {
        shutdown_with_timeout_called: Arc::new(AtomicBool::new(false)),
        resource_set: Arc::new(AtomicBool::new(false)),
    });
    let logs = ResilientLogExporter::new(ForwardingLogExporter {
        shutdown_with_timeout_called: Arc::new(AtomicBool::new(false)),
        resource_set: Arc::new(AtomicBool::new(false)),
    });
    let metrics = ResilientMetricExporter::new(ForwardingMetricExporter {
        shutdown_with_timeout_called: Arc::new(AtomicBool::new(false)),
    });

    assert_eq!(format!("{span:?}"), "ResilientSpanExporter");
    assert_eq!(format!("{logs:?}"), "ResilientLogExporter");
    assert_eq!(format!("{metrics:?}"), "ResilientMetricExporter");
    assert_eq!(metrics.temporality(), Temporality::Delta);
}

#[test]
fn resilient_exporter_shutdown_with_timeout_forwards_to_inner_exporter() {
    let _guard = acquire_test_state_lock();

    let span_called = Arc::new(AtomicBool::new(false));
    let mut span = ResilientSpanExporter::new(ForwardingSpanExporter {
        shutdown_with_timeout_called: span_called.clone(),
        resource_set: Arc::new(AtomicBool::new(false)),
    });
    span.shutdown_with_timeout(Duration::from_millis(1))
        .expect("span shutdown should succeed");
    assert!(span_called.load(Ordering::SeqCst));

    let log_called = Arc::new(AtomicBool::new(false));
    let log = ResilientLogExporter::new(ForwardingLogExporter {
        shutdown_with_timeout_called: log_called.clone(),
        resource_set: Arc::new(AtomicBool::new(false)),
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

#[test]
fn resilient_span_exporter_forwards_resource_updates() {
    let _guard = acquire_test_state_lock();

    let resource_set = Arc::new(AtomicBool::new(false));
    let mut span = ResilientSpanExporter::new(ForwardingSpanExporter {
        shutdown_with_timeout_called: Arc::new(AtomicBool::new(false)),
        resource_set: Arc::clone(&resource_set),
    });

    span.set_resource(&Resource::builder().build());
    assert!(resource_set.load(Ordering::SeqCst));

    let log_resource_set = Arc::new(AtomicBool::new(false));
    let mut log = ResilientLogExporter::new(ForwardingLogExporter {
        shutdown_with_timeout_called: Arc::new(AtomicBool::new(false)),
        resource_set: Arc::clone(&log_resource_set),
    });
    log.set_resource(&Resource::builder().build());
    assert!(log_resource_set.load(Ordering::SeqCst));
}
