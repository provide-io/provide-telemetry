// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use provide_telemetry::context::{bind_context, get_context};
use provide_telemetry::health::{get_health_snapshot, record_export_failure};
use provide_telemetry::{get_secret_patterns, register_secret_pattern};
use provide_telemetry::sampling::Signal;
use provide_telemetry::schema::{get_strict_schema, set_strict_schema};
use provide_telemetry::testing::{reset_telemetry_state, reset_trace_context};
use provide_telemetry::tracer::{get_trace_context, set_trace_context};
use regex::Regex;
use serde_json::json;
use std::sync::{Mutex, OnceLock};

static TEST_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn test_lock() -> &'static Mutex<()> {
    TEST_LOCK.get_or_init(|| Mutex::new(()))
}

#[test]
fn testing_test_reset_telemetry_state_clears_context_and_health() {
    let _guard = test_lock().lock().expect("test lock poisoned");
    let _context_guard = bind_context([("user_id", json!("u1"))]);
    record_export_failure(Signal::Logs);

    assert_eq!(get_context().get("user_id"), Some(&json!("u1")));
    assert_eq!(get_health_snapshot().export_failures_logs, 1);

    reset_telemetry_state();

    assert!(!get_context().contains_key("user_id"));
    assert_eq!(get_health_snapshot().export_failures_logs, 0);
}

#[test]
fn testing_test_reset_trace_context_clears_manually_set_trace_context() {
    let _guard = test_lock().lock().expect("test lock poisoned");
    let _trace_guard = set_trace_context(Some("abc123".to_string()), Some("def456".to_string()));
    assert_eq!(
        get_trace_context()
            .get("trace_id")
            .and_then(|value: &Option<String>| value.clone()),
        Some("abc123".to_string())
    );

    reset_trace_context();

    assert_eq!(
        get_trace_context()
            .get("trace_id")
            .and_then(|value: &Option<String>| value.clone()),
        None
    );
}

#[test]
fn testing_test_reset_telemetry_state_clears_strict_schema() {
    let _guard = test_lock().lock().expect("test lock poisoned");
    set_strict_schema(true);
    assert!(get_strict_schema(), "strict_schema must be true after set");

    reset_telemetry_state();

    assert!(
        !get_strict_schema(),
        "reset_telemetry_state must clear STRICT_SCHEMA to false"
    );
}

#[test]
fn testing_test_reset_telemetry_state_clears_custom_secret_patterns() {
    let _guard = test_lock().lock().expect("test lock poisoned");
    let baseline = get_secret_patterns().len();
    register_secret_pattern(
        "testing.reset.secret",
        Regex::new(r"RESET-[A-Z0-9]{10,}").expect("pattern must compile"),
    );
    assert!(
        get_secret_patterns().len() > baseline,
        "custom secret pattern registration must increase the visible pattern set"
    );

    reset_telemetry_state();

    assert_eq!(
        get_secret_patterns().len(),
        baseline,
        "reset_telemetry_state must clear custom secret patterns"
    );
}

#[test]
fn testing_test_reset_helpers_are_idempotent() {
    let _guard = test_lock().lock().expect("test lock poisoned");
    reset_telemetry_state();
    reset_telemetry_state();
    reset_trace_context();
    reset_trace_context();
}
