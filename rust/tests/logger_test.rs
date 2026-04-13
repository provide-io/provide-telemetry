// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use std::sync::{Mutex, OnceLock};

use provide_telemetry::{
    bind_context, configure_logging, enable_console_capture_for_tests,
    enable_json_capture_for_tests, get_logger, reset_logging_config_for_tests,
    set_as_global_logger, take_console_capture, take_json_capture, trace, Logger, LoggingConfig,
};

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

#[test]
fn logger_test_console_format_writes_readable_line() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    std::env::set_var("PROVIDE_LOG_FORMAT", "console");
    std::env::set_var("PROVIDE_LOG_INCLUDE_TIMESTAMP", "false");
    enable_console_capture_for_tests();

    let logger = get_logger(Some("tests.console_output"));
    logger.warn("console.parity.check");

    let raw = take_console_capture();
    std::env::remove_var("PROVIDE_LOG_FORMAT");
    std::env::remove_var("PROVIDE_LOG_INCLUDE_TIMESTAMP");
    Logger::drain_events_for_tests();

    let line = String::from_utf8(raw).expect("utf8");
    let line = line.trim();
    assert!(!line.is_empty(), "expected console output");
    assert!(line.contains("WARN"), "line must contain level: {line}");
    assert!(line.contains("console.parity.check"), "line must contain message: {line}");
    assert!(line.contains("tests.console_output"), "line must contain target: {line}");
    assert!(!line.starts_with("20"), "timestamp must be absent when disabled: {line}");
}

#[test]
fn logger_test_configure_logging_overrides_env() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    // Env says JSON; programmatic override says console — override wins.
    std::env::set_var("PROVIDE_LOG_FORMAT", "json");
    let mut cfg = provide_telemetry::LoggingConfig::default();
    cfg.fmt = "console".to_string();
    cfg.include_timestamp = false;
    configure_logging(cfg);
    enable_json_capture_for_tests();
    enable_console_capture_for_tests();

    let logger = get_logger(Some("tests.configure"));
    logger.info("configure.override.check");

    let json_raw = take_json_capture();
    let console_raw = take_console_capture();
    std::env::remove_var("PROVIDE_LOG_FORMAT");
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    assert!(json_raw.is_empty(), "override to console must suppress JSON emit");
    assert!(!console_raw.is_empty(), "override to console must produce console output");
}

#[test]
fn logger_test_log_trait_routes_to_events() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    // set_as_global_logger may fail if already set by another test run; that is fine.
    let _ = set_as_global_logger();
    enable_json_capture_for_tests();
    std::env::set_var("PROVIDE_LOG_FORMAT", "json");
    std::env::set_var("PROVIDE_LOG_INCLUDE_TIMESTAMP", "false");

    log::info!(target: "tests.log_trait", "log.trait.parity");

    let raw = take_json_capture();
    std::env::remove_var("PROVIDE_LOG_FORMAT");
    std::env::remove_var("PROVIDE_LOG_INCLUDE_TIMESTAMP");
    Logger::drain_events_for_tests();

    let line = String::from_utf8(raw).expect("utf8");
    let line = line.trim();
    assert!(!line.is_empty(), "log::info! must produce JSON output");
    let parsed: serde_json::Value = serde_json::from_str(line).expect("valid JSON");
    assert_eq!(parsed["msg"], "log.trait.parity");
    assert_eq!(parsed["level"], "INFO");
    assert_eq!(parsed["logger_name"], "tests.log_trait");
}

#[test]
fn logger_test_log_trait_respects_level_filter() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let _ = set_as_global_logger();
    // Configure to INFO — DEBUG must be filtered out.
    let mut cfg = provide_telemetry::LoggingConfig::default();
    cfg.level = "INFO".to_string();
    cfg.fmt = "json".to_string();
    cfg.include_timestamp = false;
    configure_logging(cfg);
    enable_json_capture_for_tests();

    log::debug!(target: "tests.log_filter", "should.be.filtered");
    log::info!(target: "tests.log_filter", "should.pass");

    let raw = take_json_capture();
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    let output = String::from_utf8(raw).expect("utf8");
    assert!(!output.contains("should.be.filtered"), "DEBUG must be filtered at INFO level");
    assert!(output.contains("should.pass"), "INFO must pass through at INFO level");
}

#[test]
fn logger_test_console_format_includes_timestamp_when_enabled() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let cfg = LoggingConfig { fmt: "console".to_string(), include_timestamp: true, ..LoggingConfig::default() };
    configure_logging(cfg);
    enable_console_capture_for_tests();

    let logger = get_logger(Some("tests.console_ts"));
    logger.info("console.timestamp.enabled");

    let raw = take_console_capture();
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    let line = String::from_utf8(raw).expect("utf8");
    let line = line.trim();
    assert!(line.starts_with("20"), "timestamp must appear when enabled: {line}");
    assert!(line.contains('T'), "timestamp must have T separator: {line}");
}

#[test]
fn logger_test_console_format_includes_context_fields() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let cfg = LoggingConfig { fmt: "console".to_string(), include_timestamp: false, ..LoggingConfig::default() };
    configure_logging(cfg);
    enable_console_capture_for_tests();

    let _ctx = bind_context([("request_id".to_string(), serde_json::Value::String("ctx-abc".into()))]);
    let logger = get_logger(Some("tests.console_ctx"));
    logger.info("console.context.fields");
    drop(_ctx);

    let raw = take_console_capture();
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    let line = String::from_utf8(raw).expect("utf8");
    let line = line.trim();
    assert!(line.contains("request_id"), "context key must appear in console line: {line}");
    assert!(line.contains("ctx-abc"), "context value must appear in console line: {line}");
}

#[test]
fn logger_test_log_trait_level_warn_filters_info() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let _ = set_as_global_logger();
    let cfg = LoggingConfig { level: "WARN".to_string(), fmt: "json".to_string(), include_timestamp: false, ..LoggingConfig::default() };
    configure_logging(cfg);
    enable_json_capture_for_tests();

    log::info!(target: "tests.warn_lvl", "info.filtered");
    log::warn!(target: "tests.warn_lvl", "warn.passes");
    log::error!(target: "tests.warn_lvl", "error.passes");

    let output = String::from_utf8(take_json_capture()).expect("utf8");
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    assert!(!output.contains("info.filtered"), "INFO must be filtered at WARN level");
    assert!(output.contains("warn.passes"), "WARN must pass at WARN level");
    assert!(output.contains("error.passes"), "ERROR must pass at WARN level");
}

#[test]
fn logger_test_log_trait_level_error_filters_warn() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let _ = set_as_global_logger();
    let cfg = LoggingConfig { level: "ERROR".to_string(), fmt: "json".to_string(), include_timestamp: false, ..LoggingConfig::default() };
    configure_logging(cfg);
    enable_json_capture_for_tests();

    log::warn!(target: "tests.error_lvl", "warn.filtered");
    log::error!(target: "tests.error_lvl", "error.passes");

    let output = String::from_utf8(take_json_capture()).expect("utf8");
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    assert!(!output.contains("warn.filtered"), "WARN must be filtered at ERROR level");
    assert!(output.contains("error.passes"), "ERROR must pass at ERROR level");
}

#[test]
fn logger_test_log_trait_level_debug_allows_debug() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let _ = set_as_global_logger();
    let cfg = LoggingConfig { level: "DEBUG".to_string(), fmt: "json".to_string(), include_timestamp: false, ..LoggingConfig::default() };
    configure_logging(cfg);
    enable_json_capture_for_tests();

    log::debug!(target: "tests.debug_lvl", "debug.passes");
    log::info!(target: "tests.debug_lvl", "info.passes");

    let output = String::from_utf8(take_json_capture()).expect("utf8");
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    assert!(output.contains("debug.passes"), "DEBUG must pass at DEBUG level");
    assert!(output.contains("info.passes"), "INFO must pass at DEBUG level");
}

#[test]
fn logger_test_log_trait_level_trace_allows_trace() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let _ = set_as_global_logger();
    let cfg = LoggingConfig { level: "TRACE".to_string(), fmt: "json".to_string(), include_timestamp: false, ..LoggingConfig::default() };
    configure_logging(cfg);
    enable_json_capture_for_tests();

    log::trace!(target: "tests.trace_lvl", "trace.passes");
    log::debug!(target: "tests.trace_lvl", "debug.passes");

    let output = String::from_utf8(take_json_capture()).expect("utf8");
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    assert!(output.contains("trace.passes"), "TRACE must pass at TRACE level");
    assert!(output.contains("debug.passes"), "DEBUG must pass at TRACE level");
}

#[test]
fn logger_test_log_trait_level_aliases_warning_and_critical() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let _ = set_as_global_logger();

    // WARNING is an alias for WARN.
    let cfg = LoggingConfig { level: "WARNING".to_string(), fmt: "json".to_string(), include_timestamp: false, ..LoggingConfig::default() };
    configure_logging(cfg);
    enable_json_capture_for_tests();
    log::info!(target: "tests.alias_lvl", "info.filtered.warning");
    log::warn!(target: "tests.alias_lvl", "warn.passes.warning");
    let out1 = String::from_utf8(take_json_capture()).expect("utf8");
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();
    assert!(!out1.contains("info.filtered.warning"), "INFO filtered under WARNING alias");
    assert!(out1.contains("warn.passes.warning"), "WARN passes under WARNING alias");

    // CRITICAL is an alias for ERROR.
    let cfg2 = LoggingConfig { level: "CRITICAL".to_string(), fmt: "json".to_string(), include_timestamp: false, ..LoggingConfig::default() };
    configure_logging(cfg2);
    enable_json_capture_for_tests();
    log::warn!(target: "tests.alias_lvl", "warn.filtered.critical");
    log::error!(target: "tests.alias_lvl", "error.passes.critical");
    let out2 = String::from_utf8(take_json_capture()).expect("utf8");
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();
    assert!(!out2.contains("warn.filtered.critical"), "WARN filtered under CRITICAL alias");
    assert!(out2.contains("error.passes.critical"), "ERROR passes under CRITICAL alias");
}
