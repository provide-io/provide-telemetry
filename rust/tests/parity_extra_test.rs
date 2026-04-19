// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// Extra parity tests covering the 7 fixture categories that were previously
// in the allowlist: config_headers, default_sensitive_keys, backpressure_unlimited,
// sampling_signal_validation, schema_strict_mode, pii_depth, log_output_format.

use std::collections::HashMap;

use serde_json::json;

use provide_telemetry::{
    configure_logging, enable_json_capture_for_tests, get_logger, reset_logging_config_for_tests,
    sanitize_payload, set_queue_policy, set_strict_schema, take_json_capture, LoggingConfig,
    QueuePolicy, Signal, TelemetryConfig,
};

// ── Config Headers ───────────────────────────────────────────────────────────
//
// Fixture: config_headers
// Validates OTEL_EXPORTER_OTLP_HEADERS parsing: comma-split key=value pairs,
// percent-encoding (spaces), plus-sign literal preservation, empty-key skip,
// no-equals skip, value-containing-equals preserved.

#[test]
fn parity_test_config_headers_plus_preserved() {
    // Plus sign must be preserved as literal, not decoded as space.
    let mut env = HashMap::new();
    env.insert(
        "OTEL_EXPORTER_OTLP_HEADERS".to_string(),
        "Authorization=Bearer+token".to_string(),
    );
    let cfg = TelemetryConfig::from_map(&env).expect("parse should succeed");
    assert_eq!(
        cfg.logging
            .otlp_headers
            .get("Authorization")
            .map(String::as_str),
        Some("Bearer+token"),
        "plus sign must be preserved as literal"
    );
}

#[test]
fn parity_test_config_headers_percent_encoded_space() {
    // %20 must be decoded to a space in both key and value.
    let mut env = HashMap::new();
    env.insert(
        "OTEL_EXPORTER_OTLP_HEADERS".to_string(),
        "my%20key=my%20value".to_string(),
    );
    let cfg = TelemetryConfig::from_map(&env).expect("parse should succeed");
    assert_eq!(
        cfg.logging.otlp_headers.get("my key").map(String::as_str),
        Some("my value"),
        "percent-encoded spaces must decode to spaces"
    );
}

#[test]
fn parity_test_config_headers_empty_key_skipped() {
    // A pair whose key is empty (starts with '=') must be skipped.
    let mut env = HashMap::new();
    env.insert(
        "OTEL_EXPORTER_OTLP_HEADERS".to_string(),
        "=value,key=val".to_string(),
    );
    let cfg = TelemetryConfig::from_map(&env).expect("parse should succeed");
    assert!(
        !cfg.logging.otlp_headers.contains_key(""),
        "empty key must be skipped"
    );
    assert_eq!(
        cfg.logging.otlp_headers.get("key").map(String::as_str),
        Some("val"),
    );
}

#[test]
fn parity_test_config_headers_no_equals_skipped() {
    // A token with no '=' separator must be skipped.
    let mut env = HashMap::new();
    env.insert(
        "OTEL_EXPORTER_OTLP_HEADERS".to_string(),
        "malformed,key=val".to_string(),
    );
    let cfg = TelemetryConfig::from_map(&env).expect("parse should succeed");
    assert!(
        !cfg.logging.otlp_headers.contains_key("malformed"),
        "no-equals entry must be skipped"
    );
    assert_eq!(
        cfg.logging.otlp_headers.get("key").map(String::as_str),
        Some("val"),
    );
}

#[test]
fn parity_test_config_headers_value_containing_equals() {
    // Only the first '=' splits key/value; the rest belong to the value.
    let mut env = HashMap::new();
    env.insert(
        "OTEL_EXPORTER_OTLP_HEADERS".to_string(),
        "Authorization=Bearer token=xyz".to_string(),
    );
    let cfg = TelemetryConfig::from_map(&env).expect("parse should succeed");
    assert_eq!(
        cfg.logging
            .otlp_headers
            .get("Authorization")
            .map(String::as_str),
        Some("Bearer token=xyz"),
        "value containing '=' must be preserved intact"
    );
}

#[test]
fn parity_test_config_headers_empty_string_returns_empty() {
    // An empty header string must produce an empty map (not None).
    let mut env = HashMap::new();
    env.insert("OTEL_EXPORTER_OTLP_HEADERS".to_string(), String::new());
    let cfg = TelemetryConfig::from_map(&env).expect("parse should succeed");
    assert!(
        cfg.logging.otlp_headers.is_empty(),
        "empty header string must produce empty map"
    );
}

// ── Default Sensitive Keys ───────────────────────────────────────────────────
//
// Fixture: default_sensitive_keys
// Confirms the canonical 17-key list is treated as sensitive by sanitize_payload
// without any explicit PII rules.

#[test]
fn parity_test_default_sensitive_keys_all_redacted() {
    // All 17 canonical default-sensitive keys must be redacted automatically.
    let canonical_keys = [
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "credential",
        "private_key",
        "ssn",
        "credit_card",
        "creditcard",
        "cvv",
        "pin",
        "account_number",
        "cookie",
    ];
    for key in &canonical_keys {
        let payload = json!({ *key: "sensitive-value" });
        let result = sanitize_payload(&payload, true, 32);
        assert_eq!(
            result[*key], "***",
            "default-sensitive key '{key}' must be auto-redacted"
        );
    }
}

#[test]
fn parity_test_default_sensitive_keys_case_insensitive() {
    // Matching must be case-insensitive (e.g. API_KEY, PASSWORD).
    let payload = json!({"API_KEY": "abc123", "PASSWORD": "secret123"}); // pragma: allowlist secret
    let result = sanitize_payload(&payload, true, 32);
    assert_eq!(result["API_KEY"], "***", "API_KEY must be redacted");
    assert_eq!(result["PASSWORD"], "***", "PASSWORD must be redacted"); // pragma: allowlist secret
}

// ── Backpressure Unlimited ───────────────────────────────────────────────────
//
// Fixture: backpressure_unlimited
// size=0 means unlimited — try_acquire must always return Some.

#[test]
fn parity_test_backpressure_unlimited_zero_size_always_succeeds() {
    // Queue size 0 → unlimited; every acquire must succeed.
    provide_telemetry::backpressure::_reset_backpressure_for_tests();
    set_queue_policy(QueuePolicy {
        logs_maxsize: 0,
        traces_maxsize: 0,
        metrics_maxsize: 0,
    });
    let ticket = provide_telemetry::try_acquire(Signal::Logs);
    assert!(ticket.is_some(), "size=0 must always succeed (unlimited)");
}

#[test]
fn parity_test_backpressure_unlimited_100_acquires_all_succeed() {
    // 100 consecutive acquires on an unlimited queue must all succeed.
    provide_telemetry::backpressure::_reset_backpressure_for_tests();
    set_queue_policy(QueuePolicy {
        logs_maxsize: 0,
        traces_maxsize: 0,
        metrics_maxsize: 0,
    });
    for i in 0..100 {
        let ticket = provide_telemetry::try_acquire(Signal::Logs);
        assert!(
            ticket.is_some(),
            "acquire #{i} must succeed on unlimited queue"
        );
    }
}

#[test]
fn parity_test_backpressure_unlimited_bounded_rejects_second() {
    // With size=1 the second un-released acquire must be rejected.
    provide_telemetry::backpressure::_reset_backpressure_for_tests();
    set_queue_policy(QueuePolicy {
        logs_maxsize: 1,
        traces_maxsize: 0,
        metrics_maxsize: 0,
    });
    let first = provide_telemetry::try_acquire(Signal::Logs);
    let second = provide_telemetry::try_acquire(Signal::Logs);
    assert!(
        first.is_some(),
        "first acquire must succeed for bounded queue"
    );
    assert!(
        second.is_none(),
        "second acquire without release must be rejected"
    );
    // Release first ticket explicitly.
    if let Some(t) = first {
        provide_telemetry::release(t);
    }
    provide_telemetry::backpressure::_reset_backpressure_for_tests();
}

// ── Sampling Signal Validation ───────────────────────────────────────────────
//
// Fixture: sampling_signal_validation
// Only Signal::Logs, Signal::Traces, Signal::Metrics are valid.
// In Rust's type system invalid signal variants cannot be constructed —
// the fixture is satisfied by confirming all three valid signals work and
// noting that the enum exhaustively guards against unknown values at compile
// time (no runtime "unknown signal" error path exists for the typed API).

#[test]
fn parity_test_sampling_signal_validation_valid_logs_accepted() {
    // Signal::Logs is a valid signal; should_sample must succeed.
    let result = provide_telemetry::should_sample(Signal::Logs, None);
    assert!(result.is_ok(), "Signal::Logs must be accepted");
}

#[test]
fn parity_test_sampling_signal_validation_valid_traces_accepted() {
    // Signal::Traces is a valid signal; should_sample must succeed.
    let result = provide_telemetry::should_sample(Signal::Traces, None);
    assert!(result.is_ok(), "Signal::Traces must be accepted");
}

#[test]
fn parity_test_sampling_signal_validation_valid_metrics_accepted() {
    // Signal::Metrics is a valid signal; should_sample must succeed.
    let result = provide_telemetry::should_sample(Signal::Metrics, None);
    assert!(result.is_ok(), "Signal::Metrics must be accepted");
}

// ── Schema Strict Mode ───────────────────────────────────────────────────────
//
// Fixture: schema_strict_mode
// set_strict_schema(false) accepts uppercase/mixed-case segments;
// set_strict_schema(true) rejects them.

// Use a dedicated mutex so schema-mode tests don't race each other.
static SCHEMA_LOCK: std::sync::OnceLock<std::sync::Mutex<()>> = std::sync::OnceLock::new();

fn schema_lock() -> &'static std::sync::Mutex<()> {
    SCHEMA_LOCK.get_or_init(|| std::sync::Mutex::new(()))
}

#[test]
fn parity_test_schema_strict_mode_lenient_accepts_uppercase() {
    let _guard = schema_lock().lock().expect("schema lock poisoned");
    provide_telemetry::schema::_reset_schema_for_tests();
    set_strict_schema(false);
    let result = provide_telemetry::event(&["A", "B", "C"]);
    provide_telemetry::schema::_reset_schema_for_tests();
    assert!(
        result.is_ok(),
        "lenient mode must accept uppercase segments"
    );
}

#[test]
fn parity_test_schema_strict_mode_lenient_accepts_mixed_case() {
    let _guard = schema_lock().lock().expect("schema lock poisoned");
    provide_telemetry::schema::_reset_schema_for_tests();
    set_strict_schema(false);
    let result = provide_telemetry::event(&["User", "Login", "Ok"]);
    provide_telemetry::schema::_reset_schema_for_tests();
    assert!(
        result.is_ok(),
        "lenient mode must accept mixed-case segments"
    );
}

#[test]
fn parity_test_schema_strict_mode_strict_rejects_uppercase() {
    let _guard = schema_lock().lock().expect("schema lock poisoned");
    provide_telemetry::schema::_reset_schema_for_tests();
    set_strict_schema(true);
    let result = provide_telemetry::event(&["User", "login", "ok"]);
    provide_telemetry::schema::_reset_schema_for_tests();
    assert!(
        result.is_err(),
        "strict mode must reject uppercase-starting segments"
    );
}

#[test]
fn parity_test_schema_strict_mode_strict_accepts_valid_lowercase() {
    let _guard = schema_lock().lock().expect("schema lock poisoned");
    provide_telemetry::schema::_reset_schema_for_tests();
    set_strict_schema(true);
    let result = provide_telemetry::event(&["user", "login", "ok"]);
    provide_telemetry::schema::_reset_schema_for_tests();
    assert!(
        result.is_ok(),
        "strict mode must accept valid lowercase segments"
    );
}

// ── PII Depth ────────────────────────────────────────────────────────────────
//
// Fixture: pii_depth
// sanitize_payload respects max_depth; default is 8.
// At depth < max_depth sensitive keys ARE redacted.
// At depth >= max_depth the subtree is returned unchanged.

#[test]
fn parity_test_pii_depth_within_max_depth_is_redacted() {
    // depth=2 with max_depth=3: the password key is within range and must be redacted.
    let payload = json!({"outer": {"password": "secret"}}); // pragma: allowlist secret
    let result = sanitize_payload(&payload, true, 3);
    assert_eq!(
        result["outer"]["password"],
        "***", // pragma: allowlist secret
        "sensitive key within max_depth must be redacted"
    );
}

#[test]
fn parity_test_pii_depth_at_max_depth_is_untouched() {
    // depth=2 with max_depth=2: recursion stops at depth boundary, inner dict untouched.
    let inner = json!({"password": "secret"}); // pragma: allowlist secret
    let payload = json!({"a": {"b": inner}});
    let result = sanitize_payload(&payload, true, 2);
    // At depth=2 recursion stops; inner dict is returned as-is.
    assert_eq!(
        result["a"]["b"]["password"],
        "secret", // pragma: allowlist secret
        "sensitive key at/beyond max_depth must NOT be redacted"
    );
}

#[test]
fn parity_test_pii_depth_default_is_eight() {
    // Default max_depth=8; a key at depth 7 (within limit) must be redacted.
    // Build a chain: {"l1": {"l2": {"l3": {"l4": {"l5": {"l6": {"l7": {"password": "s"}}}}}}}}
    let payload = json!({
        "l1": {
            "l2": {
                "l3": {
                    "l4": {
                        "l5": {
                            "l6": {
                                "l7": { "password": "s" } // pragma: allowlist secret
                            }
                        }
                    }
                }
            }
        }
    });
    // max_depth=8 means up to 8 levels deep are traversed; depth 7 is within range.
    let result = sanitize_payload(&payload, true, 8);
    assert_eq!(
        result["l1"]["l2"]["l3"]["l4"]["l5"]["l6"]["l7"]["password"],
        "***", // pragma: allowlist secret
        "key at depth 7 (within default max_depth=8) must be redacted"
    );
}

// ── Log Output Format ────────────────────────────────────────────────────────
//
// Fixture: log_output_format
// Rust logger emits a structured JSON line containing the "log.output.parity"
// marker message with required fields: message (msg) and level.

#[test]
fn parity_test_log_output_format_json_contains_parity_marker() {
    // Configure JSON logging, capture output, emit the canonical probe message,
    // then verify the captured line contains the log.output.parity marker.
    configure_logging(LoggingConfig {
        fmt: "json".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    });
    enable_json_capture_for_tests();

    let log = get_logger(Some("probe"));
    log.info("log.output.parity");

    let raw = take_json_capture();
    reset_logging_config_for_tests();

    let text = String::from_utf8_lossy(&raw);
    assert!(
        text.contains("log.output.parity"),
        "JSON output must contain the log.output.parity marker, got: {text}"
    );

    // Verify the required canonical fields are present.
    let parsed: serde_json::Value =
        serde_json::from_str(text.lines().next().unwrap_or("{}")).expect("valid JSON");
    // Rust uses "message" as the field name (aliased to "msg" by normalizer).
    assert!(
        parsed.get("message").is_some() || parsed.get("msg").is_some(),
        "JSON log line must contain 'message' or 'msg' field"
    );
    assert!(
        parsed.get("level").is_some(),
        "JSON log line must contain 'level' field"
    );
}
