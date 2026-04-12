// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use std::sync::{Mutex, OnceLock};

use provide_telemetry::testing::reset_telemetry_state;
use provide_telemetry::{get_logger, trace, Logger};

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
fn logger_test_debug_and_warn_levels_are_captured() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    reset_telemetry_state();
    let logger = get_logger(Some("tests.logger.levels"));

    logger.debug("debug-msg");
    logger.warn("warn-msg");

    let events = Logger::drain_events_for_tests();
    assert_eq!(events.len(), 2);
    assert_eq!(events[0].level, "DEBUG");
    assert_eq!(events[0].message, "debug-msg");
    assert_eq!(events[1].level, "WARN");
    assert_eq!(events[1].message, "warn-msg");
}

#[test]
fn logger_test_unknown_level_stored_verbatim_in_buffer() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    reset_telemetry_state();
    let logger = get_logger(Some("tests.logger.custom"));

    // "TRACE" is not one of the four known levels — falls through to INFO in
    // tracing, but the raw string is preserved in the test-capture buffer.
    logger.log("TRACE", "trace-msg");

    let events = Logger::drain_events_for_tests();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].level, "TRACE");
    assert_eq!(events[0].message, "trace-msg");
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
fn logger_test_target_getter_returns_configured_name() {
    // Kills: replace Logger::target -> &str with "" or "xyzzy"
    let logger = get_logger(Some("my.service.logger"));
    assert_eq!(logger.target(), "my.service.logger");

    let null = null_logger(Some("my.null.logger"));
    assert_eq!(null.target(), "my.null.logger");

    let buf = buffer_logger(Some("my.buffer.logger"));
    assert_eq!(buf.target(), "my.buffer.logger");
}

#[test]
fn logger_test_tracing_levels_match_log_method() {
    // Kills: delete match arm "DEBUG", "WARN", or "ERROR" in Logger::log.
    // The EVENTS buffer stores the raw level string before the match, so buffer
    // checks pass even with deleted arms. This test uses a thread-local subscriber
    // to verify the *actual tracing level* emitted for each method.
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    Logger::drain_events_for_tests(); // clear any residual events before we start
    let levels = Arc::new(Mutex::new(Vec::<String>::new()));
    let logger = get_logger(Some("tests.tracing.levels"));
    tracing::subscriber::with_default(LevelCapture(levels.clone()), || {
        logger.debug("d");
        logger.info("i");
        logger.warn("w");
        logger.error("e");
    });
    Logger::drain_events_for_tests(); // clean up so subsequent tests see a fresh buffer
    let captured = levels.lock().expect("level capture lock").clone();
    assert!(
        captured.contains(&"DEBUG".to_string()),
        "debug() must emit at DEBUG level; got {captured:?}"
    );
    assert!(
        captured.contains(&"INFO".to_string()),
        "info() must emit at INFO level; got {captured:?}"
    );
    assert!(
        captured.contains(&"WARN".to_string()),
        "warn() must emit at WARN level; got {captured:?}"
    );
    assert!(
        captured.contains(&"ERROR".to_string()),
        "error() must emit at ERROR level; got {captured:?}"
    );
}

#[test]
fn logger_test_buffer_logger_all_methods_store_events() {
    // Kills: replace BufferLogger::debug/info/warn/error with ()
    // Each convenience method must delegate to log() and appear in drain().
    let buf = buffer_logger(Some("tests.buf.methods"));
    buf.debug("d-msg");
    buf.info("i-msg");
    buf.warn("w-msg");
    buf.error("e-msg");
    let events = buf.drain();
    assert_eq!(events.len(), 4);
    assert_eq!(events[0].level, "DEBUG");
    assert_eq!(events[0].message, "d-msg");
    assert_eq!(events[1].level, "INFO");
    assert_eq!(events[1].message, "i-msg");
    assert_eq!(events[2].level, "WARN");
    assert_eq!(events[2].message, "w-msg");
    assert_eq!(events[3].level, "ERROR");
    assert_eq!(events[3].message, "e-msg");
}

#[test]
fn logger_test_buffer_caps_at_max_fallback_events() {
    // Kills: replace < with <= in the buf.len() < MAX_FALLBACK_EVENTS guard.
    // With <=, the 1001st event would be stored; with <, it must be dropped.
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    Logger::drain_events_for_tests(); // clear residual events from other tests
    let logger = get_logger(Some("tests.buffer.cap"));
    for _ in 0..1001 {
        logger.info("x");
    }
    let events = Logger::drain_events_for_tests();
    assert_eq!(
        events.len(),
        1000,
        "buffer must not exceed MAX_FALLBACK_EVENTS (1000)"
    );
}
