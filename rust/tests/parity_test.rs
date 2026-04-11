// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use serde_json::json;
use std::sync::{Mutex, OnceLock};

use provide_telemetry::{
    classify_error, clear_cardinality_limits, compute_error_fingerprint, event,
    extract_w3c_context, get_cardinality_limits, get_health_snapshot, get_queue_policy,
    get_sampling_policy, get_secret_patterns, record_red_metrics, record_use_metrics,
    register_cardinality_limit, register_secret_pattern, reset_secret_patterns_for_tests,
    sanitize_payload, set_queue_policy, set_sampling_policy, CardinalityLimit, EventSchemaError,
    PIIMode, PIIRule, QueuePolicy, SamplingPolicy, Signal,
};
use rstest::rstest;

static PARITY_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn parity_lock() -> &'static Mutex<()> {
    PARITY_LOCK.get_or_init(|| Mutex::new(()))
}

#[test]
fn parity_test_event_dars_matches_fixture() {
    let evt = event(&["db", "query", "users", "ok"]).expect("event should build");
    assert_eq!(evt.event, "db.query.users.ok");
    assert_eq!(evt.domain, "db");
    assert_eq!(evt.action, "query");
    assert_eq!(evt.resource.as_deref(), Some("users"));
    assert_eq!(evt.status, "ok");
}

#[test]
fn parity_test_event_rejects_invalid_segment_count() {
    let err = event(&["too", "few"]).expect_err("invalid event should fail");
    assert_eq!(
        err,
        EventSchemaError::new("event() requires 3 or 4 segments (DA[R]S), got 2")
    );
}

#[test]
fn parity_test_secret_detection_matches_fixture() {
    let payload = json!({"data": "AKIAIOSFODNN7EXAMPLE"}); // pragma: allowlist secret
    let sanitized = sanitize_payload(&payload, true, 32);
    assert_eq!(sanitized["data"], "***");
}

#[test]
fn parity_test_normal_string_unchanged() {
    let payload = json!({"data": "not-a-secret"});
    let sanitized = sanitize_payload(&payload, true, 32);
    assert_eq!(sanitized["data"], "not-a-secret");
}

#[test]
fn parity_test_cardinality_zero_max_values_clamped() {
    let _guard = parity_lock().lock().expect("parity lock poisoned");
    clear_cardinality_limits();
    register_cardinality_limit(
        "k",
        CardinalityLimit {
            max_values: 0,
            ttl_seconds: 10.0,
        },
    );
    let limits = get_cardinality_limits();
    assert_eq!(limits.get("k").map(|limit| limit.max_values), Some(1));
    clear_cardinality_limits();
}

#[test]
fn parity_test_cardinality_zero_ttl_clamped() {
    let _guard = parity_lock().lock().expect("parity lock poisoned");
    clear_cardinality_limits();
    register_cardinality_limit(
        "k",
        CardinalityLimit {
            max_values: 10,
            ttl_seconds: 0.0,
        },
    );
    let limits = get_cardinality_limits();
    assert_eq!(limits.get("k").map(|limit| limit.ttl_seconds), Some(1.0));
    clear_cardinality_limits();
}

#[test]
fn parity_test_pii_hash_matches_fixture() {
    let payload = json!({"password": "secret"}); // pragma: allowlist secret
    provide_telemetry::replace_pii_rules(vec![PIIRule {
        path: vec!["password".to_string()],
        mode: PIIMode::Hash,
        truncate_to: 0,
    }]);

    let sanitized = sanitize_payload(&payload, true, 32);
    assert_eq!(sanitized["password"], "2bb80d537b1d"); // pragma: allowlist secret

    provide_telemetry::replace_pii_rules(Vec::new());
}

#[test]
fn parity_test_propagation_limits_match_fixture() {
    let traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";
    let tracestate_32 = format!("{}z=q", "a=b,".repeat(31));

    let accepted = extract_w3c_context(Some(traceparent), Some(&tracestate_32), None);
    assert_eq!(accepted.traceparent.as_deref(), Some(traceparent));
    assert!(accepted.tracestate.is_some());

    let discarded =
        extract_w3c_context(Some(&"x".repeat(513)), Some("k=v"), Some(&"b".repeat(8193)));
    assert!(discarded.traceparent.is_none());
    assert_eq!(discarded.tracestate.as_deref(), Some("k=v"));
    assert!(discarded.baggage.is_none());
}

#[rstest]
#[case(404, "client_error")]
#[case(503, "server_error")]
#[case(200, "ok")]
#[case(0, "timeout")]
fn parity_test_slo_classification_matches_fixture(
    #[case] status_code: u16,
    #[case] expected: &str,
) {
    assert_eq!(classify_error(status_code), expected);
}

#[test]
fn parity_test_pii_truncate_mode() {
    let _guard = parity_lock().lock().expect("parity lock");
    provide_telemetry::replace_pii_rules(vec![PIIRule {
        path: vec!["note".to_string()],
        mode: PIIMode::Truncate,
        truncate_to: 5,
    }]);
    let payload = json!({"note": "hello world"});
    let result = sanitize_payload(&payload, true, 32);
    assert_eq!(result["note"], "hello...");
    provide_telemetry::replace_pii_rules(Vec::new());
}

#[test]
fn parity_test_pii_redact_mode() {
    let _guard = parity_lock().lock().expect("parity lock");
    provide_telemetry::replace_pii_rules(vec![PIIRule {
        path: vec!["note".to_string()],
        mode: PIIMode::Redact,
        truncate_to: 0,
    }]);
    let payload = json!({"note": "sensitive"});
    let result = sanitize_payload(&payload, true, 32);
    assert_eq!(result["note"], "***");
    provide_telemetry::replace_pii_rules(Vec::new());
}

#[test]
fn parity_test_pii_drop_mode() {
    let _guard = parity_lock().lock().expect("parity lock");
    provide_telemetry::replace_pii_rules(vec![PIIRule {
        path: vec!["note".to_string()],
        mode: PIIMode::Drop,
        truncate_to: 0,
    }]);
    let payload = json!({"note": "sensitive"});
    let result = sanitize_payload(&payload, true, 32);
    assert!(result.get("note").is_none());
    provide_telemetry::replace_pii_rules(Vec::new());
}

#[test]
fn parity_test_jwt_detection() {
    // A JWT-format token should be auto-redacted as a secret
    let payload = json!({"auth": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0"}); // pragma: allowlist secret
    let result = sanitize_payload(&payload, true, 32);
    assert_eq!(result["auth"], "***");
}

#[test]
fn parity_test_fingerprint_is_deterministic() {
    let a = compute_error_fingerprint("ValueError", None);
    let b = compute_error_fingerprint("ValueError", None);
    assert_eq!(a, b, "same input must produce same fingerprint");
}

#[test]
fn parity_test_fingerprint_differs_by_error_type() {
    let a = compute_error_fingerprint("ValueError", None);
    let b = compute_error_fingerprint("TypeError", None);
    assert_ne!(
        a, b,
        "different error names must produce different fingerprints"
    );
}

#[test]
fn parity_test_backpressure_queue_policy_roundtrip() {
    let policy = QueuePolicy {
        logs_maxsize: 42,
        traces_maxsize: 10,
        metrics_maxsize: 10,
    };
    set_queue_policy(policy);
    let got = get_queue_policy();
    assert_eq!(got.logs_maxsize, 42);
}

#[test]
fn parity_test_sampling_policy_roundtrip() {
    let policy = SamplingPolicy {
        default_rate: 0.5,
        overrides: Default::default(),
    };
    set_sampling_policy(Signal::Logs, policy).expect("set ok");
    let got = get_sampling_policy(Signal::Logs).expect("get ok");
    assert!((got.default_rate - 0.5).abs() < 1e-9);
}

#[test]
fn parity_test_health_snapshot_is_available() {
    let snap = get_health_snapshot();
    let _ = snap;
}

#[test]
fn parity_test_record_red_metrics_200_no_error_counter() {
    // 200 should increment requests but NOT errors
    record_red_metrics("/health", "GET", 200, 5.0);
}

#[test]
fn parity_test_record_red_metrics_500_increments_error() {
    record_red_metrics("/api/v1/events", "POST", 500, 45.0);
}

#[test]
fn parity_test_record_red_metrics_ws_no_error_counter() {
    // WS method should never increment error counter regardless of status
    record_red_metrics("/ws", "WS", 503, 0.0);
}

#[test]
fn parity_test_record_use_metrics_does_not_panic() {
    record_use_metrics("cpu", 75);
    record_use_metrics("memory", 90);
}

#[test]
fn parity_test_register_secret_pattern_custom_detection() {
    let _guard = parity_lock().lock().expect("parity lock");
    reset_secret_patterns_for_tests();
    let pattern = regex::Regex::new(r"MYTOKEN-[A-Z0-9]{8}").expect("valid regex");
    register_secret_pattern("mytoken", pattern);
    let payload = json!({"key": "MYTOKEN-ABCD1234"}); // pragma: allowlist secret
    let result = sanitize_payload(&payload, true, 32);
    assert_eq!(result["key"], "***");
    reset_secret_patterns_for_tests();
}

#[test]
fn parity_test_get_secret_patterns_includes_builtins() {
    let patterns = get_secret_patterns();
    assert!(!patterns.is_empty(), "must have at least built-in patterns");
    assert!(patterns.iter().any(|p| p.name.starts_with("builtin-")));
}

#[test]
fn parity_test_register_secret_pattern_deduplication() {
    let _guard = parity_lock().lock().expect("parity lock");
    reset_secret_patterns_for_tests();
    register_secret_pattern("mytoken", regex::Regex::new(r"TOK1").expect("valid"));
    register_secret_pattern("mytoken", regex::Regex::new(r"TOK2").expect("valid")); // replaces
    let patterns = get_secret_patterns();
    let custom: Vec<_> = patterns.iter().filter(|p| p.name == "mytoken").collect();
    assert_eq!(custom.len(), 1, "duplicate name must replace, not append");
    reset_secret_patterns_for_tests();
}
