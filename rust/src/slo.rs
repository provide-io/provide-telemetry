// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::OnceLock;

use crate::metrics::{counter, gauge, histogram, Counter, Gauge, Histogram};

static SLO_INITIALIZED: AtomicBool = AtomicBool::new(false);
static SLO_ERROR_COUNT: AtomicU64 = AtomicU64::new(0);
static SLO_REQUEST_COUNT: AtomicU64 = AtomicU64::new(0);

static RED_REQUESTS: OnceLock<Counter> = OnceLock::new();
static RED_ERRORS: OnceLock<Counter> = OnceLock::new();
static RED_DURATION: OnceLock<Histogram> = OnceLock::new();
static USE_UTILIZATION: OnceLock<Gauge> = OnceLock::new();

pub fn record_red_metrics(route: &str, method: &str, status_code: u16, duration_ms: f64) {
    SLO_INITIALIZED.store(true, Ordering::SeqCst);
    let attrs: BTreeMap<String, String> = [
        ("route".to_string(), route.to_string()),
        ("method".to_string(), method.to_string()),
        ("status_code".to_string(), status_code.to_string()),
    ]
    .into_iter()
    .collect();
    RED_REQUESTS
        .get_or_init(|| counter("http.requests.total", Some("Total HTTP requests"), None))
        .add(1.0, Some(attrs.clone()));
    if method != "WS" && status_code >= 500 {
        RED_ERRORS
            .get_or_init(|| counter("http.errors.total", Some("Total HTTP errors"), None))
            .add(1.0, Some(attrs.clone()));
    }
    RED_DURATION
        .get_or_init(|| {
            histogram(
                "http.request.duration_ms",
                Some("HTTP request latency"),
                Some("ms"),
            )
        })
        .record(duration_ms, Some(attrs));
}

pub fn record_use_metrics(resource: &str, utilization_percent: i32) {
    SLO_INITIALIZED.store(true, Ordering::SeqCst);
    let mut attrs = BTreeMap::new();
    attrs.insert("resource".to_string(), resource.to_string());
    USE_UTILIZATION
        .get_or_init(|| {
            gauge(
                "resource.utilization.percent",
                Some("Resource utilization"),
                Some("%"),
            )
        })
        .set(utilization_percent as f64, Some(attrs));
}

pub fn classify_error(status_code: u16) -> String {
    SLO_INITIALIZED.store(true, Ordering::SeqCst);
    let attrs: BTreeMap<String, String> = [
        ("route".to_string(), route.to_string()),
        ("method".to_string(), method.to_string()),
        ("status_code".to_string(), status_code.to_string()),
    ]
    .into_iter()
    .collect();
    SLO_REQUEST_COUNT.fetch_add(1, Ordering::SeqCst);
    RED_REQUESTS
        .get_or_init(|| counter("http.requests.total", Some("Total HTTP requests"), None))
        .add(1.0, Some(attrs.clone()));
    if method != "WS" && status_code >= 500 {
        SLO_ERROR_COUNT.fetch_add(1, Ordering::SeqCst);
        RED_ERRORS
            .get_or_init(|| counter("http.errors.total", Some("Total HTTP errors"), None))
            .add(1.0, Some(attrs.clone()));
    }
    RED_DURATION
        .get_or_init(|| {
            histogram(
                "http.request.duration_ms",
                Some("HTTP request latency"),
                Some("ms"),
            )
        })
        .record(duration_ms, Some(attrs));
}

pub fn record_use_metrics(resource: &str, utilization_percent: i32) {
    SLO_INITIALIZED.store(true, Ordering::SeqCst);
    let mut attrs = BTreeMap::new();
    attrs.insert("resource".to_string(), resource.to_string());
    USE_UTILIZATION
        .get_or_init(|| {
            gauge(
                "resource.utilization.percent",
                Some("Resource utilization"),
                Some("%"),
            )
        })
        .set(utilization_percent as f64, Some(attrs));
}

/// Classify an error by exception name and/or HTTP status code.
///
/// Returns a map with both legacy keys (`error_type`, `error_code`,
/// `error_name`) and spec-aligned keys (`error.type`, `error.category`,
/// `error.severity`, `http.status_code`) matching the Python reference.
pub fn classify_error(error_name: &str, status_code: Option<u16>) -> BTreeMap<String, String> {
    SLO_INITIALIZED.store(true, Ordering::SeqCst);
    let code = status_code.unwrap_or(0);
    let is_timeout = error_name.to_ascii_lowercase().contains("timeout")
        || code == 0
        || code == 408
        || code == 504;

    let (category, severity, error_type) = if is_timeout {
        ("timeout", "info", "internal")
    } else if (500..=599).contains(&code) {
        ("server_error", "critical", "server")
    } else if (400..=499).contains(&code) {
        (
            "client_error",
            if code == 429 { "critical" } else { "warning" },
            "client",
        )
    } else {
        ("unclassified", "info", "internal")
    };

    [
        ("error_type", error_type),
        ("error_code", &code.to_string()),
        ("error_name", error_name),
        ("error.type", error_name),
        ("error.category", category),
        ("error.severity", severity),
        ("http.status_code", &code.to_string()),
    ]
    .into_iter()
    .map(|(k, v)| (k.to_string(), v.to_string()))
    .collect()
}

pub fn slo_initialized_for_tests() -> bool {
    SLO_INITIALIZED.load(Ordering::SeqCst)
}

pub fn get_error_count_for_tests() -> u64 {
    SLO_ERROR_COUNT.load(Ordering::SeqCst)
}

pub fn get_request_count_for_tests() -> u64 {
    SLO_REQUEST_COUNT.load(Ordering::SeqCst)
}

pub fn reset_slo_for_tests() {
    SLO_INITIALIZED.store(false, Ordering::SeqCst);
    SLO_ERROR_COUNT.store(0, Ordering::SeqCst);
    SLO_REQUEST_COUNT.store(0, Ordering::SeqCst);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testing::acquire_test_state_lock;

    #[test]
    fn slo_test_reset_helper_clears_initialized_flag() {
        let _guard = acquire_test_state_lock();
        reset_slo_for_tests();
        assert!(!slo_initialized_for_tests());

        assert_eq!(
            classify_error("SomeError", Some(503))["error.category"],
            "server_error"
        );
        assert!(slo_initialized_for_tests());

        reset_slo_for_tests();
        assert!(!slo_initialized_for_tests());
    }
}
