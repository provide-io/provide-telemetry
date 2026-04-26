// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use super::*;

use crate::logger::{configure_logging, reset_logging_config_for_tests};
use crate::testing::acquire_test_state_lock;

fn reset_emit_state() {
    reset_logging_config_for_tests();
    let _ = take_json_capture();
    let _ = take_console_capture();
    std::env::remove_var("PROVIDE_LOG_FORMAT");
    std::env::remove_var("PROVIDE_LOG_INCLUDE_TIMESTAMP");
}

fn test_event() -> LogEvent {
    let mut context = std::collections::BTreeMap::new();
    context.insert("user_id".to_string(), Value::String("u-1".to_string()));
    context.insert("ok".to_string(), Value::Bool(true));
    LogEvent {
        level: "INFO".to_string(),
        target: "tests.emit".to_string(),
        message: "emit.message".to_string(),
        context,
        trace_id: Some("0123456789abcdef0123456789abcdef".to_string()),
        span_id: Some("0123456789abcdef".to_string()),
        event_metadata: None,
    }
}

#[test]
fn emit_test_take_capture_defaults_to_empty_buffers() {
    let _guard = acquire_test_state_lock();
    reset_emit_state();

    assert!(take_json_capture().is_empty());
    assert!(take_console_capture().is_empty());
}

#[test]
fn emit_test_emit_json_line_includes_context_trace_span_and_logger_name() {
    let _guard = acquire_test_state_lock();
    reset_emit_state();
    enable_json_capture_for_tests();

    emit_json_line(&test_event(), false);

    let raw = String::from_utf8(take_json_capture()).expect("json capture should be utf8");
    let parsed: Value =
        serde_json::from_str(raw.trim()).expect("captured line should parse as json");
    assert_eq!(parsed["message"], "emit.message");
    assert_eq!(parsed["level"], "INFO");
    assert_eq!(parsed["logger_name"], "tests.emit");
    assert_eq!(parsed["user_id"], "u-1");
    assert_eq!(parsed["ok"], true);
    assert_eq!(parsed["trace_id"], "0123456789abcdef0123456789abcdef");
    assert_eq!(parsed["span_id"], "0123456789abcdef");
    assert!(parsed.get("timestamp").is_none());
}

#[test]
fn emit_test_emit_if_json_respects_format_and_timestamp_flag() {
    let _guard = acquire_test_state_lock();
    reset_emit_state();
    enable_json_capture_for_tests();
    configure_logging(crate::config::LoggingConfig {
        fmt: "json".to_string(),
        include_timestamp: true,
        ..crate::config::LoggingConfig::default()
    });

    emit_if_json(&test_event());

    let raw = String::from_utf8(take_json_capture()).expect("json capture should be utf8");
    let parsed: Value =
        serde_json::from_str(raw.trim()).expect("captured line should parse as json");
    assert!(parsed
        .get("timestamp")
        .and_then(Value::as_str)
        .is_some_and(|value| value.ends_with('Z')));

    reset_emit_state();
    enable_json_capture_for_tests();
    configure_logging(crate::config::LoggingConfig {
        fmt: "console".to_string(),
        include_timestamp: false,
        ..crate::config::LoggingConfig::default()
    });
    emit_if_json(&test_event());
    assert!(take_json_capture().is_empty());
}

#[test]
fn emit_test_console_format_renders_expected_line_and_respects_json_mode() {
    let _guard = acquire_test_state_lock();
    reset_emit_state();
    enable_console_capture_for_tests();
    configure_logging(crate::config::LoggingConfig {
        fmt: "console".to_string(),
        include_timestamp: false,
        ..crate::config::LoggingConfig::default()
    });

    let line = format_console_line(&test_event(), false);
    assert!(line.contains("INFO"));
    assert!(line.contains("tests.emit"));
    assert!(line.contains("emit.message"));
    assert!(line.contains("user_id=\"u-1\""));

    emit_if_console(&test_event());
    let captured =
        String::from_utf8(take_console_capture()).expect("console capture should be utf8");
    assert!(captured.contains("emit.message"));

    reset_emit_state();
    enable_console_capture_for_tests();
    configure_logging(crate::config::LoggingConfig {
        fmt: "json".to_string(),
        include_timestamp: false,
        ..crate::config::LoggingConfig::default()
    });
    emit_if_console(&test_event());
    assert!(take_console_capture().is_empty());
}

#[test]
fn emit_test_iso8601_helper_covers_january_and_april_paths() {
    let _guard = acquire_test_state_lock();
    reset_emit_state();

    assert_eq!(iso8601_from_unix_parts(0, 0), "1970-01-01T00:00:00.000Z");
    assert_eq!(
        iso8601_from_unix_parts(90 * 86_400, 7),
        "1970-04-01T00:00:00.007Z"
    );
}

// Kills: `-` -> `+` on `doe / 146_096` in the Howard Hinnant year-of-era
// formula. The correction term only matters at doe == 146096 (the last day of
// a 400-year era). ts=951782400 is 2000-02-29 UTC and lands at exactly that
// boundary; under the mutant the formula yields 2000-03-01 instead.
//
// Also kills: `+` -> `-` on `doe / 36_524` and `-` -> `/` on `doe / 146_096`
// (both at line 70). The 2200-03-01 case (ts=7263216000, doe=73048 in era 5)
// has doe/36524 == 2 and doe/146096 == 0, so flipping the `+` between the
// 1460 and 36524 terms shifts yoe from 200 to 199, yielding "2200-02-29"
// (an invalid date in a non-leap century year) — clearly distinguishable.
#[test]
fn emit_test_iso8601_helper_handles_400_year_era_boundary() {
    let _guard = acquire_test_state_lock();
    reset_emit_state();

    assert_eq!(
        iso8601_from_unix_parts(951_782_400, 0),
        "2000-02-29T00:00:00.000Z"
    );
    assert_eq!(
        iso8601_from_unix_parts(7_263_216_000, 0),
        "2200-03-01T00:00:00.000Z"
    );
}

#[test]
fn emit_test_emit_json_line_falls_back_to_stderr_without_capture() {
    let _guard = acquire_test_state_lock();
    reset_emit_state();

    emit_json_line(&test_event(), false);
}
