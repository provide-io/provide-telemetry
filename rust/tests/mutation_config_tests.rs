// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// Mutation tests for config.rs

use std::collections::HashMap;

use provide_telemetry::{setup_telemetry, TelemetryConfig};

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
        cfg.logging.otlp_headers.get("x-bad").is_none(),
        "header with bare % at end should be silently skipped"
    );
}

/// Only one char after % — needs two hex digits, so this is also invalid.
#[test]
fn test_percent_encoding_one_hex_digit_is_rejected() {
    let cfg = config_with_header("x-bad=value%4").expect("config-level parse must succeed");
    assert!(
        cfg.logging.otlp_headers.get("x-bad").is_none(),
        "header with %<one-digit> should be silently skipped"
    );
}

/// Non-hex character in first position after % — invalid.
#[test]
fn test_percent_encoding_non_hex_first_char_is_rejected() {
    let cfg = config_with_header("x-bad=value%GF").expect("config-level parse must succeed");
    assert!(
        cfg.logging.otlp_headers.get("x-bad").is_none(),
        "header with %G (non-hex first digit) should be silently skipped"
    );
}

/// Non-hex character in second position after % — invalid.
#[test]
fn test_percent_encoding_non_hex_second_char_is_rejected() {
    let cfg = config_with_header("x-bad=value%4Z").expect("config-level parse must succeed");
    assert!(
        cfg.logging.otlp_headers.get("x-bad").is_none(),
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
