// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use std::sync::{Mutex, OnceLock};

use provide_telemetry::{enable_json_capture_for_tests, get_logger, take_json_capture, trace, Logger};

static LOGGER_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn logger_lock() -> &'static Mutex<()> {
    LOGGER_LOCK.get_or_init(|| Mutex::new(()))
}

#[test]
fn logger_test_logging_works_without_otel() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let logger = get_logger(Some("tests.logger"));

    logger.info("logger.test.info");
    logger.debug("logger.test.debug");
    logger.error("logger.test.error");

    let events = Logger::drain_events_for_tests();
    assert_eq!(events.len(), 3);
    assert_eq!(events[0].target, "tests.logger");
    assert_eq!(events[0].level, "INFO");
    assert_eq!(events[0].message, "logger.test.info");
    assert_eq!(events[2].level, "ERROR");
}

#[test]
fn logger_test_trace_wrapper_works_without_otel() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");

    let observed = std::sync::Mutex::new((None::<String>, None::<String>));
    let result = trace("tests.trace.wrapper", || {
        let trace_context = provide_telemetry::get_trace_context();
        *observed.lock().expect("observed lock poisoned") = (
            trace_context
                .get("trace_id")
                .and_then(std::clone::Clone::clone),
            trace_context
                .get("span_id")
                .and_then(std::clone::Clone::clone),
        );
        41 + 1
    });
    let trace_context = provide_telemetry::get_trace_context();
    let observed = observed.lock().expect("observed lock poisoned");

    assert_eq!(result, 42);
    assert_eq!(observed.0.as_ref().map(std::string::String::len), Some(32));
    assert_eq!(observed.1.as_ref().map(std::string::String::len), Some(16));
    assert_eq!(trace_context.get("trace_id"), Some(&None));
    assert_eq!(trace_context.get("span_id"), Some(&None));
}

#[test]
fn logger_test_json_emit_produces_canonical_fields() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    // Arrange: enable capture and set JSON format without timestamp.
    std::env::set_var("PROVIDE_LOG_FORMAT", "json");
    std::env::set_var("PROVIDE_LOG_INCLUDE_TIMESTAMP", "false");
    enable_json_capture_for_tests();

    let logger = get_logger(Some("tests.json_emit"));
    logger.info("log.output.parity");

    let raw = take_json_capture();
    std::env::remove_var("PROVIDE_LOG_FORMAT");
    std::env::remove_var("PROVIDE_LOG_INCLUDE_TIMESTAMP");

    let line = String::from_utf8(raw).expect("utf8");
    let line = line.trim();
    assert!(!line.is_empty(), "expected a JSON line in capture buffer");

    let parsed: serde_json::Value = serde_json::from_str(line).expect("valid JSON");
    assert_eq!(parsed["msg"], "log.output.parity", "msg field must match");
    assert_eq!(parsed["level"], "INFO", "level must be uppercase INFO");
    assert_eq!(parsed["logger_name"], "tests.json_emit", "logger_name must match target");
    assert!(parsed.get("timestamp").is_none(), "timestamp must be absent when disabled");
    Logger::drain_events_for_tests();
}

#[test]
fn logger_test_json_emit_includes_timestamp_by_default() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    std::env::set_var("PROVIDE_LOG_FORMAT", "json");
    std::env::remove_var("PROVIDE_LOG_INCLUDE_TIMESTAMP");
    enable_json_capture_for_tests();

    let logger = get_logger(Some("tests.ts"));
    logger.warn("log.timestamp.check");

    let raw = take_json_capture();
    std::env::remove_var("PROVIDE_LOG_FORMAT");

    let line = String::from_utf8(raw).expect("utf8");
    let parsed: serde_json::Value = serde_json::from_str(line.trim()).expect("valid JSON");
    assert_eq!(parsed["level"], "WARN");
    let ts = parsed["timestamp"].as_str().expect("timestamp must be a string");
    // ISO 8601 pattern: 2026-04-13T00:00:00.000Z
    assert!(
        ts.len() == 24 && ts.ends_with('Z') && ts.contains('T'),
        "timestamp {ts:?} must match ISO 8601"
    );
    Logger::drain_events_for_tests();
}

#[test]
fn logger_test_no_json_emit_in_console_format() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    std::env::set_var("PROVIDE_LOG_FORMAT", "console");
    enable_json_capture_for_tests();

    let logger = get_logger(Some("tests.console"));
    logger.debug("should.not.emit.json");

    let raw = take_json_capture();
    std::env::remove_var("PROVIDE_LOG_FORMAT");

    assert!(raw.is_empty(), "no JSON should be captured in console format");
    // Drain event buffer to keep tests clean.
    Logger::drain_events_for_tests();
}
