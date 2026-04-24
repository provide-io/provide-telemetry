// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use super::*;
use crate::config::LoggingConfig;
use crate::logger::emit::{
    enable_pretty_capture_for_tests, take_console_capture, take_json_capture, take_pretty_capture,
};
use crate::logger::{configure_logging, reset_logging_config_for_tests, LogEvent};
use crate::testing::acquire_test_state_lock;
use serde_json::Value;
use std::collections::BTreeMap;

fn reset_state() {
    reset_logging_config_for_tests();
    let _ = take_json_capture();
    let _ = take_console_capture();
    let _ = take_pretty_capture();
    std::env::remove_var("PROVIDE_LOG_FORMAT");
    std::env::remove_var("PROVIDE_LOG_INCLUDE_TIMESTAMP");
    std::env::remove_var("PROVIDE_LOG_PRETTY_KEY_COLOR");
    std::env::remove_var("PROVIDE_LOG_PRETTY_VALUE_COLOR");
    std::env::remove_var("PROVIDE_LOG_PRETTY_FIELDS");
}

fn sample_event(level: &str) -> LogEvent {
    let mut ctx = BTreeMap::new();
    ctx.insert("user_id".to_string(), Value::String("u-1".to_string()));
    ctx.insert("ok".to_string(), Value::Bool(true));
    ctx.insert("count".to_string(), Value::from(42));
    LogEvent {
        level: level.to_string(),
        target: "tests.pretty".to_string(),
        message: "pretty.message".to_string(),
        context: ctx,
        trace_id: Some("0123456789abcdef0123456789abcdef".to_string()),
        span_id: Some("0123456789abcdef".to_string()),
        event_metadata: None,
    }
}

#[test]
fn pretty_test_non_tty_path_emits_no_ansi_escapes() {
    let _guard = acquire_test_state_lock();
    reset_state();
    let cfg = LoggingConfig {
        fmt: "pretty".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    };

    let line = format_pretty_line_with_colors(&sample_event("INFO"), &cfg, false);

    assert!(
        !line.contains("\x1b["),
        "plain output must be ANSI-free: {line}"
    );
    assert!(line.contains("[info     ]"));
    assert!(line.contains("tests.pretty"));
    assert!(line.contains("pretty.message"));
    assert!(line.contains("user_id=\"u-1\""));
    assert!(line.contains("ok=true"));
    assert!(line.contains("count=42"));
    assert!(line.contains("trace_id=\"0123456789abcdef0123456789abcdef\""));
    assert!(line.contains("span_id=\"0123456789abcdef\""));
}

#[test]
fn pretty_test_logger_name_is_rendered_as_key_value() {
    let _guard = acquire_test_state_lock();
    reset_state();
    let cfg = LoggingConfig {
        fmt: "pretty".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    };

    let line = format_pretty_line_with_colors(&sample_event("INFO"), &cfg, false);

    assert!(line.contains("logger_name=\"tests.pretty\""));
    assert!(
        !line.contains("] tests.pretty pretty.message"),
        "logger target must not be emitted as an unkeyed token: {line}"
    );
}

#[test]
fn pretty_test_pretty_fields_env_filters_context_and_standard_fields() {
    let _guard = acquire_test_state_lock();
    reset_state();
    std::env::set_var("PROVIDE_LOG_PRETTY_FIELDS", "logger_name,user_id,trace_id");
    let cfg = LoggingConfig {
        fmt: "pretty".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    };

    let line = format_pretty_line_with_colors(&sample_event("INFO"), &cfg, false);

    assert!(line.contains("logger_name=\"tests.pretty\""));
    assert!(line.contains("user_id=\"u-1\""));
    assert!(line.contains("trace_id=\"0123456789abcdef0123456789abcdef\""));
    assert!(!line.contains("ok=true"));
    assert!(!line.contains("count=42"));
    assert!(!line.contains("span_id=\"0123456789abcdef\""));
}

#[test]
fn pretty_test_tty_path_applies_ansi_colors_for_keys_and_values() {
    let _guard = acquire_test_state_lock();
    reset_state();
    std::env::set_var("PROVIDE_LOG_PRETTY_KEY_COLOR", "bold");
    std::env::set_var("PROVIDE_LOG_PRETTY_VALUE_COLOR", "red");
    let cfg = LoggingConfig {
        fmt: "pretty".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    };

    let line = format_pretty_line_with_colors(&sample_event("WARN"), &cfg, true);

    // Level colored and bracketed
    assert!(line.contains("[\x1b[33mwarn     \x1b[0m]"));
    // Bold key + red value
    assert!(line.contains("\x1b[1muser_id\x1b[0m=\x1b[31m\"u-1\"\x1b[0m"));
    // Reset escape present at least once
    assert!(line.contains("\x1b[0m"));
}

#[test]
fn pretty_test_level_colors_cover_all_supported_levels() {
    let _guard = acquire_test_state_lock();
    reset_state();
    let cfg = LoggingConfig {
        fmt: "pretty".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    };

    let levels = [
        ("trace", "\x1b[36m"),
        ("debug", "\x1b[34m"),
        ("info", "\x1b[32m"),
        ("warning", "\x1b[33m"),
        ("warn", "\x1b[33m"),
        ("error", "\x1b[31m"),
        ("critical", "\x1b[31;1m"),
        ("fatal", "\x1b[31;1m"),
    ];
    for (lvl, expected_esc) in levels {
        let line = format_pretty_line_with_colors(&sample_event(lvl), &cfg, true);
        assert!(
            line.contains(expected_esc),
            "level {lvl} missing color {expected_esc:?} in {line}"
        );
    }

    // Unknown levels fall through with no color but still get padded + bracketed.
    let line = format_pretty_line_with_colors(&sample_event("BOGUS"), &cfg, true);
    assert!(line.contains("[bogus    ]"));
    assert!(!line.contains("[\x1b["));
}

#[test]
fn pretty_test_resolve_named_color_covers_all_known_and_unknown() {
    assert_eq!(resolve_named_color("dim"), ANSI_DIM);
    assert_eq!(resolve_named_color("bold"), ANSI_BOLD);
    assert_eq!(resolve_named_color("red"), ANSI_RED);
    assert_eq!(resolve_named_color("green"), ANSI_GREEN);
    assert_eq!(resolve_named_color("yellow"), ANSI_YELLOW);
    assert_eq!(resolve_named_color("blue"), ANSI_BLUE);
    assert_eq!(resolve_named_color("cyan"), ANSI_CYAN);
    assert_eq!(resolve_named_color("white"), ANSI_WHITE);
    assert_eq!(resolve_named_color(""), "");
    assert_eq!(resolve_named_color("none"), "");
    assert_eq!(resolve_named_color("  DIM "), ANSI_DIM);
    assert_eq!(resolve_named_color("mauve"), "");
}

#[test]
fn pretty_test_timestamp_included_when_configured() {
    let _guard = acquire_test_state_lock();
    reset_state();
    let cfg = LoggingConfig {
        fmt: "pretty".to_string(),
        include_timestamp: true,
        ..LoggingConfig::default()
    };

    let line_plain = format_pretty_line_with_colors(&sample_event("INFO"), &cfg, false);
    assert!(line_plain.contains('T') && line_plain.contains('Z'));
    assert!(!line_plain.contains("\x1b["));

    let line_colored = format_pretty_line_with_colors(&sample_event("INFO"), &cfg, true);
    // Dim wraps timestamp in color mode
    assert!(line_colored.contains("\x1b[2m"));
    assert!(line_colored.contains("\x1b[0m"));
}

#[test]
fn pretty_test_empty_key_value_colors_leave_text_uncolored() {
    let _guard = acquire_test_state_lock();
    reset_state();
    std::env::set_var("PROVIDE_LOG_PRETTY_KEY_COLOR", "");
    std::env::set_var("PROVIDE_LOG_PRETTY_VALUE_COLOR", "");
    let cfg = LoggingConfig {
        fmt: "pretty".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    };

    let line = format_pretty_line_with_colors(&sample_event("INFO"), &cfg, true);
    // Level is still colored (green), but key/value pairs must not be wrapped.
    assert!(line.contains("user_id=\"u-1\""));
    assert!(!line.contains("\x1b[1muser_id"));
    assert!(!line.contains("\x1b[2muser_id"));
}

#[test]
fn pretty_test_emit_if_pretty_writes_to_capture_when_format_is_pretty() {
    let _guard = acquire_test_state_lock();
    reset_state();
    enable_pretty_capture_for_tests();
    configure_logging(LoggingConfig {
        fmt: "pretty".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    });

    crate::logger::emit::emit_if_pretty(&sample_event("INFO"));

    let captured = String::from_utf8(take_pretty_capture()).expect("pretty capture must be utf8");
    assert!(captured.contains("pretty.message"));
    assert!(captured.ends_with('\n'));
}

#[test]
fn pretty_test_emit_if_pretty_no_op_when_format_is_not_pretty() {
    let _guard = acquire_test_state_lock();
    reset_state();
    enable_pretty_capture_for_tests();
    configure_logging(LoggingConfig {
        fmt: "console".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    });

    crate::logger::emit::emit_if_pretty(&sample_event("INFO"));

    assert!(take_pretty_capture().is_empty());
}

#[test]
fn pretty_test_emit_if_console_suppressed_when_format_is_pretty() {
    let _guard = acquire_test_state_lock();
    reset_state();
    crate::logger::emit::enable_console_capture_for_tests();
    enable_pretty_capture_for_tests();
    configure_logging(LoggingConfig {
        fmt: "pretty".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    });

    crate::logger::emit::emit_if_console(&sample_event("INFO"));
    crate::logger::emit::emit_if_pretty(&sample_event("INFO"));

    assert!(take_console_capture().is_empty());
    assert!(!take_pretty_capture().is_empty());
}

#[test]
fn pretty_test_stderr_is_tty_does_not_panic() {
    // Exercised for coverage — outcome depends on how the test harness was
    // launched, so we only assert that the call returns without panicking.
    let _ = super::stderr_is_tty();
}

#[test]
fn pretty_test_emit_if_pretty_falls_back_to_stderr_without_capture() {
    let _guard = acquire_test_state_lock();
    reset_state();
    configure_logging(LoggingConfig {
        fmt: "pretty".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    });

    // Without a pretty capture buffer enabled, emit writes to stderr via
    // eprintln!. Just confirm it does not panic.
    crate::logger::emit::emit_if_pretty(&sample_event("INFO"));
}
