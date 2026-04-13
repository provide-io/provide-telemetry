// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use std::collections::HashMap;

use provide_telemetry::{redact_config, setup_telemetry, ConfigurationError, TelemetryConfig};

fn config_from(entries: &[(&str, &str)]) -> Result<TelemetryConfig, ConfigurationError> {
    let env: HashMap<String, String> = entries
        .iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect();
    TelemetryConfig::from_map(&env)
}

#[test]
fn test_telemetry_config_default() {
    let config = TelemetryConfig::default();
    assert!(!config.service_name.is_empty());
}

#[test]
fn test_telemetry_config_from_env() {
    let _config = TelemetryConfig::from_env();
}

#[test]
fn test_setup_telemetry() {
    let _ = setup_telemetry();
    let _ = setup_telemetry();
}

// --- has_invalid_percent_encoding boundary tests ---
// Reached through TelemetryConfig::from_map via OTEL_EXPORTER_OTLP_HEADERS.
// Valid encoding: key=value%2Cwith%2Ccommas → header preserved.
// Invalid encoding: k=%GX (non-hex digit) → header silently skipped.

fn config_with_header(header: &str) -> Result<TelemetryConfig, String> {
    let mut env = HashMap::new();
    env.insert("OTEL_EXPORTER_OTLP_HEADERS".to_string(), header.to_string());
    TelemetryConfig::from_map(&env).map_err(|e| e.to_string())
}

/// Valid %AB encoding — from_map must succeed and preserve the decoded value.
#[test]
fn test_percent_encoding_valid_is_accepted() {
    // %41 decodes to 'A'; the header value "hello%41world" = "helloAworld".
    let cfg = config_with_header("x-custom=hello%41world").expect("valid encoding must not fail");
    let logs_headers = &cfg.logging.otlp_headers;
    assert_eq!(
        logs_headers.get("x-custom").map(|s| s.as_str()),
        Some("helloAworld")
    );
}

/// % at the very end of the string — too few chars → invalid.
#[test]
fn test_percent_encoding_percent_at_end_is_rejected() {
    // When encoding is invalid the header pair is silently skipped (not an error at the
    // config level), so the key simply won't appear.
    let cfg = config_with_header("x-bad=value%").expect("config-level parse must succeed");
    assert!(
        !cfg.logging.otlp_headers.contains_key("x-bad"),
        "header with bare % at end should be silently skipped"
    );
}

/// Only one char after % — needs two hex digits, so this is also invalid.
#[test]
fn test_percent_encoding_one_hex_digit_is_rejected() {
    let cfg = config_with_header("x-bad=value%4").expect("config-level parse must succeed");
    assert!(
        !cfg.logging.otlp_headers.contains_key("x-bad"),
        "header with %<one-digit> should be silently skipped"
    );
}

/// Non-hex character in first position after % — invalid.
#[test]
fn test_percent_encoding_non_hex_first_char_is_rejected() {
    let cfg = config_with_header("x-bad=value%GF").expect("config-level parse must succeed");
    assert!(
        !cfg.logging.otlp_headers.contains_key("x-bad"),
        "header with %G (non-hex first digit) should be silently skipped"
    );
}

/// Non-hex character in second position after % — invalid.
#[test]
fn test_percent_encoding_non_hex_second_char_is_rejected() {
    let cfg = config_with_header("x-bad=value%4Z").expect("config-level parse must succeed");
    assert!(
        !cfg.logging.otlp_headers.contains_key("x-bad"),
        "header with %4Z (non-hex second digit) should be silently skipped"
    );
}

/// Exactly two hex digits at the boundary (% is the second-to-last char with one following hex) — invalid.
#[test]
fn test_percent_encoding_boundary_exactly_two_chars_after_percent_is_valid() {
    // %4F = 'O'. The entire value is "%4F" (3 chars, idx=0, idx+2=2, len=3, 2 >= 3 is false → valid).
    let cfg = config_with_header("x-ok=%4F").expect("config-level parse must succeed");
    assert_eq!(
        cfg.logging.otlp_headers.get("x-ok").map(|s| s.as_str()),
        Some("O"),
        "%4F (exactly idx+2 == len-1) must be treated as valid encoding"
    );
}

// --- parse_bool false-y values ---
// Kills: replace match guard matches!(..., "0"|"false"|"no"|"off") with false
// Without the false-y guard, "false"/"no"/"off"/"0" fall through to the Err branch.

#[test]
fn config_test_parse_bool_falsy_values_are_accepted() {
    for val in &["false", "False", "FALSE", "0", "no", "NO", "off", "OFF"] {
        let cfg = config_from(&[("PROVIDE_TRACE_ENABLED", val)])
            .unwrap_or_else(|e| panic!("{val:?} should parse as false, got error: {e}"));
        assert!(!cfg.tracing.enabled, "{val:?} must parse as false");
    }
}

// --- parse_non_negative_float edge cases ---
// Kills: replace || with && (infinity slips through), replace < with == (negatives slip through),
//        replace < with <= (zero is incorrectly rejected).

#[test]
fn config_test_non_negative_float_rejects_infinity() {
    // Kills: || → && (with &&, !is_finite() && negative is false for +inf → no error)
    let err = config_from(&[("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS", "inf")])
        .expect_err("infinity must be rejected");
    assert!(err
        .message
        .contains("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS"));
}

#[test]
fn config_test_non_negative_float_rejects_negative() {
    // Kills: < → == (only 0.0 would error; -1 would slip through)
    let err = config_from(&[("PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS", "-1")])
        .expect_err("negative float must be rejected");
    assert!(err
        .message
        .contains("PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS"));
}

#[test]
fn config_test_non_negative_float_accepts_zero() {
    // Kills: < → <= (zero would be incorrectly rejected)
    let cfg = config_from(&[("PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS", "0.0")])
        .expect("zero must be a valid non-negative float");
    assert_eq!(cfg.exporter.logs_backoff_seconds, 0.0);
}

// --- redact_config ---

#[test]
fn redact_config_masks_otlp_header_values() {
    // Kills: return cfg.clone() unchanged (no masking)
    let cfg = config_from(&[(
        "OTEL_EXPORTER_OTLP_HEADERS",
        "authorization=Bearer secret123",
    )])
    .unwrap();
    let redacted = redact_config(&cfg);
    // Keys are preserved, values replaced.
    assert!(
        redacted.logging.otlp_headers.contains_key("authorization"),
        "key must be preserved"
    );
    assert_eq!(
        redacted
            .logging
            .otlp_headers
            .get("authorization")
            .map(String::as_str),
        Some("***REDACTED***"),
        "value must be masked"
    );
}

#[test]
fn redact_config_preserves_non_header_fields() {
    // Kills: replacing all fields with defaults.
    let cfg = config_from(&[
        ("PROVIDE_TELEMETRY_SERVICE_NAME", "my-service"),
        ("PROVIDE_TELEMETRY_ENV", "prod"),
    ])
    .unwrap();
    let redacted = redact_config(&cfg);
    assert_eq!(redacted.service_name, "my-service");
    assert_eq!(redacted.environment, "prod");
}

#[test]
fn redact_config_empty_headers_unchanged() {
    // Kills: unconditionally mask even empty headers.
    let cfg = TelemetryConfig::default();
    let redacted = redact_config(&cfg);
    assert!(
        redacted.logging.otlp_headers.is_empty(),
        "empty headers must stay empty"
    );
}

#[test]
fn redact_config_does_not_mutate_original() {
    // Ensures the original is not modified.
    let cfg = config_from(&[("OTEL_EXPORTER_OTLP_HEADERS", "x-token=realvalue")]).unwrap();
    let original_value = cfg.logging.otlp_headers.get("x-token").cloned();
    let _ = redact_config(&cfg);
    assert_eq!(
        cfg.logging.otlp_headers.get("x-token").cloned(),
        original_value,
        "original config must not be mutated"
    );
}
