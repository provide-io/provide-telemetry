// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use serde_json::json;
use std::sync::{Mutex, OnceLock};

use provide_telemetry::{
    classify_error, clear_cardinality_limits, event, extract_w3c_context, get_cardinality_limits,
    register_cardinality_limit, sanitize_payload, CardinalityLimit, EventSchemaError, PIIMode,
    PIIRule,
};

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

#[test]
fn parity_test_slo_classification_matches_fixture() {
    assert_eq!(classify_error(404), "client_error");
    assert_eq!(classify_error(503), "server_error");
    assert_eq!(classify_error(200), "ok");
}
