// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::OnceLock;

use crate::metrics::{counter, gauge, histogram, Counter, Gauge, Histogram};

static SLO_INITIALIZED: AtomicBool = AtomicBool::new(false);

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
    match status_code {
        0 => "timeout".to_string(),
        400..=499 => "client_error".to_string(),
        500..=599 => "server_error".to_string(),
        _ => "ok".to_string(),
    }
}

pub fn slo_initialized_for_tests() -> bool {
    SLO_INITIALIZED.load(Ordering::SeqCst)
}

pub fn reset_slo_for_tests() {
    SLO_INITIALIZED.store(false, Ordering::SeqCst);
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

        assert_eq!(classify_error(503), "server_error");
        assert!(slo_initialized_for_tests());

        reset_slo_for_tests();
        assert!(!slo_initialized_for_tests());
    }
}
