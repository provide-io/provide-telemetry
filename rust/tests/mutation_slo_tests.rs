// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// Mutation-killing tests for slo.rs and classification.rs.
// Each test is annotated with the mutation(s) it targets.

use std::sync::{Mutex, OnceLock};

use provide_telemetry::{
    classify_error, get_error_count_for_tests, get_request_count_for_tests, record_red_metrics,
    record_use_metrics, reset_slo_for_tests, slo_initialized_for_tests,
};

static SLO_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn slo_lock() -> &'static Mutex<()> {
    SLO_LOCK.get_or_init(|| Mutex::new(()))
}

// ── classify_error boundary tests (now returns BTreeMap with rich keys) ──────

fn category(error_name: &str, code: u16) -> String {
    classify_error(error_name, Some(code))["error.category"].clone()
}

fn severity(error_name: &str, code: u16) -> String {
    classify_error(error_name, Some(code))["error.severity"].clone()
}

#[test]
fn slo_classify_error_zero_is_timeout() {
    assert_eq!(category("SomeError", 0), "timeout");
}

#[test]
fn slo_classify_error_400_is_client_error() {
    assert_eq!(category("BadReq", 400), "client_error");
}

#[test]
fn slo_classify_error_499_is_client_error() {
    assert_eq!(category("BadReq", 499), "client_error");
}

#[test]
fn slo_classify_error_500_is_server_error() {
    assert_eq!(category("InternalError", 500), "server_error");
}

#[test]
fn slo_classify_error_599_is_server_error() {
    assert_eq!(category("InternalError", 599), "server_error");
}

#[test]
fn slo_classify_error_399_is_unclassified() {
    assert_eq!(category("Unknown", 399), "unclassified");
}

#[test]
fn slo_classify_error_600_is_unclassified() {
    assert_eq!(category("Unknown", 600), "unclassified");
}

#[test]
fn slo_classify_error_200_is_unclassified() {
    assert_eq!(category("Success", 200), "unclassified");
}

#[test]
fn slo_classify_error_timeout_in_name_is_timeout() {
    assert_eq!(category("ConnectionTimeout", 200), "timeout");
}

#[test]
fn slo_classify_error_408_is_timeout() {
    assert_eq!(category("SomeError", 408), "timeout");
}

#[test]
fn slo_classify_error_504_is_timeout() {
    assert_eq!(category("SomeError", 504), "timeout");
}

#[test]
fn slo_classify_error_429_has_critical_severity() {
    assert_eq!(severity("RateLimit", 429), "critical");
}

#[test]
fn slo_classify_error_404_has_warning_severity() {
    assert_eq!(severity("NotFound", 404), "warning");
}

#[test]
fn slo_classify_error_returns_all_spec_keys() {
    let result = classify_error("TestError", Some(503));
    assert!(result.contains_key("error_type"), "short key");
    assert!(result.contains_key("error_code"), "short key");
    assert!(result.contains_key("error_name"), "short key");
    assert!(result.contains_key("error.type"), "spec key");
    assert!(result.contains_key("error.category"), "spec key");
    assert!(result.contains_key("error.severity"), "spec key");
    assert!(result.contains_key("http.status_code"), "spec key");
    assert_eq!(result["error.type"], "TestError");
    assert_eq!(result["http.status_code"], "503");
}

// ── record_red_metrics condition tests ───────────────────────────────────────
// These rely on SLO_ERROR_COUNT / SLO_REQUEST_COUNT atomics added to slo.rs
// to give observable evidence of whether the error branch was taken.

// Kills: `status_code >= 500` mutated to `status_code > 500` (boundary off-by-one).
#[test]
fn slo_red_metrics_status_500_increments_error_count() {
    let _guard = slo_lock().lock().expect("slo lock");
    reset_slo_for_tests();
    record_red_metrics("/api", "POST", 500, 10.0);
    assert_eq!(
        get_error_count_for_tests(),
        1,
        "status 500 must increment error counter (kills >= vs > mutation)"
    );
    assert_eq!(get_request_count_for_tests(), 1);
}

// Kills: `status_code >= 500` mutated to `status_code >= 501` or `> 500`.
// 499 must NOT trigger the error branch.
#[test]
fn slo_red_metrics_status_499_does_not_increment_error_count() {
    let _guard = slo_lock().lock().expect("slo lock");
    reset_slo_for_tests();
    record_red_metrics("/api", "GET", 499, 5.0);
    assert_eq!(
        get_error_count_for_tests(),
        0,
        "status 499 must not increment error counter"
    );
    assert_eq!(get_request_count_for_tests(), 1);
}

// Kills: `method != "WS"` mutated to `true` (removes WS guard).
// WS + status 503 should NOT increment error counter.
#[test]
fn slo_red_metrics_ws_method_503_does_not_increment_error_count() {
    let _guard = slo_lock().lock().expect("slo lock");
    reset_slo_for_tests();
    record_red_metrics("/ws", "WS", 503, 0.0);
    assert_eq!(
        get_error_count_for_tests(),
        0,
        "WS method must never increment error counter regardless of status"
    );
    assert_eq!(get_request_count_for_tests(), 1);
}

// Kills: `method != "WS"` mutated to `method == "WS"` (inverted guard).
// Non-WS + status 500 must increment error counter.
#[test]
fn slo_red_metrics_non_ws_method_500_increments_error_count() {
    let _guard = slo_lock().lock().expect("slo lock");
    reset_slo_for_tests();
    record_red_metrics("/api", "GET", 500, 10.0);
    assert_eq!(
        get_error_count_for_tests(),
        1,
        "non-WS method with status 500 must increment error counter"
    );
}

// Kills: `&&` mutated to `||` (changes logic to OR).
// WS + 200 should increment neither error count (with OR: WS is false but 200<500 also false — actually OK
// but with || and a 4xx WS call it would differ; cover that case below).
#[test]
fn slo_red_metrics_ws_method_200_does_not_increment_error_count() {
    let _guard = slo_lock().lock().expect("slo lock");
    reset_slo_for_tests();
    record_red_metrics("/ws", "WS", 200, 1.0);
    assert_eq!(get_error_count_for_tests(), 0);
}

// Kills: `&&` mutated to `||` — if logic is OR then WS+200 stays 0 (both false),
// but non-WS+499 would become 1 (first term true). Explicitly verify non-WS+499 = 0.
#[test]
fn slo_red_metrics_non_ws_499_does_not_increment_error_count() {
    let _guard = slo_lock().lock().expect("slo lock");
    reset_slo_for_tests();
    record_red_metrics("/page", "POST", 499, 2.0);
    assert_eq!(
        get_error_count_for_tests(),
        0,
        "non-WS with status 499 must not increment error counter (kills && -> || mutation)"
    );
}

// Kills: request counter incremented on every call regardless of condition.
#[test]
fn slo_red_metrics_request_count_always_increments() {
    let _guard = slo_lock().lock().expect("slo lock");
    reset_slo_for_tests();
    record_red_metrics("/a", "GET", 200, 1.0);
    record_red_metrics("/b", "POST", 500, 2.0);
    record_red_metrics("/c", "WS", 503, 0.0);
    assert_eq!(
        get_request_count_for_tests(),
        3,
        "every call must increment request counter"
    );
    assert_eq!(
        get_error_count_for_tests(),
        1,
        "only the POST 500 should count as an error"
    );
}

// ── record_use_metrics smoke test ─────────────────────────────────────────────
// record_use_metrics has no observable return value; this test at minimum ensures
// the function does not panic and the cast `utilization_percent as f64` is present.
#[test]
fn slo_use_metrics_does_not_panic_for_boundary_values() {
    record_use_metrics("cpu", 0);
    record_use_metrics("cpu", 100);
    record_use_metrics("cpu", i32::MAX);
    record_use_metrics("cpu", i32::MIN);
}

// Kills: `record_use_metrics` body replaced with `()` — empty body would skip
// the SLO_INITIALIZED store, leaving the flag false after the call.
#[test]
fn slo_use_metrics_sets_initialized_flag() {
    let _guard = slo_lock().lock().expect("slo lock");
    reset_slo_for_tests();
    assert!(!slo_initialized_for_tests());
    record_use_metrics("cpu", 50);
    assert!(slo_initialized_for_tests());
}
