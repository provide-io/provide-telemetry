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
    // Set level to TRACE so all level methods are tested.
    // Default is INFO which correctly filters DEBUG.
    configure_logging(LoggingConfig {
        level: "TRACE".to_string(),
        ..LoggingConfig::default()
    });
    let logger = get_logger(Some("tests.logger"));

    logger.info("logger.test.info");
    logger.debug("logger.test.debug");
    logger.error("logger.test.error");

    let events = Logger::drain_events_for_tests();
    reset_logging_config_for_tests();
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
    assert_eq!(
        parsed["message"], "log.output.parity",
        "message field must match"
    );
    assert_eq!(parsed["level"], "INFO", "level must be uppercase INFO");
    assert_eq!(
        parsed["logger_name"], "tests.json_emit",
        "logger_name must match target"
    );
    assert!(
        parsed.get("timestamp").is_none(),
        "timestamp must be absent when disabled"
    );
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
    let ts = parsed["timestamp"]
        .as_str()
        .expect("timestamp must be a string");
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

    assert!(
        raw.is_empty(),
        "no JSON should be captured in console format"
    );
    // Drain event buffer to keep tests clean.
    Logger::drain_events_for_tests();
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
    assert!(
        line.contains("console.parity.check"),
        "line must contain message: {line}"
    );
    assert!(
        line.contains("tests.console_output"),
        "line must contain target: {line}"
    );
    assert!(
        !line.starts_with("20"),
        "timestamp must be absent when disabled: {line}"
    );
}

#[test]
fn logger_test_configure_logging_overrides_env() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    // Env says JSON; programmatic override says console — override wins.
    std::env::set_var("PROVIDE_LOG_FORMAT", "json");
    let cfg = provide_telemetry::LoggingConfig {
        fmt: "console".to_string(),
        include_timestamp: false,
        ..provide_telemetry::LoggingConfig::default()
    };
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

    assert!(
        json_raw.is_empty(),
        "override to console must suppress JSON emit"
    );
    assert!(
        !console_raw.is_empty(),
        "override to console must produce console output"
    );
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
    assert_eq!(parsed["message"], "log.trait.parity");
    assert_eq!(parsed["level"], "INFO");
    assert_eq!(parsed["logger_name"], "tests.log_trait");
}

#[test]
fn logger_test_log_trait_respects_level_filter() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let _ = set_as_global_logger();
    // Configure to INFO — DEBUG must be filtered out.
    let cfg = provide_telemetry::LoggingConfig {
        level: "INFO".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..provide_telemetry::LoggingConfig::default()
    };
    configure_logging(cfg);
    enable_json_capture_for_tests();

    log::debug!(target: "tests.log_filter", "should.be.filtered");
    log::info!(target: "tests.log_filter", "should.pass");

    let raw = take_json_capture();
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    let output = String::from_utf8(raw).expect("utf8");
    assert!(
        !output.contains("should.be.filtered"),
        "DEBUG must be filtered at INFO level"
    );
    assert!(
        output.contains("should.pass"),
        "INFO must pass through at INFO level"
    );
}

#[test]
fn logger_test_log_trait_respects_module_level_override() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let _ = set_as_global_logger();
    // Global INFO, but module "tests.mod_override" gets DEBUG.
    // Without the fix, enabled() uses global INFO and drops the DEBUG record
    // before log_event() can apply the module override.
    let cfg = LoggingConfig {
        level: "INFO".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        module_levels: {
            let mut m = std::collections::HashMap::new();
            m.insert("tests.mod_override".to_string(), "DEBUG".to_string());
            m
        },
        ..LoggingConfig::default()
    };
    configure_logging(cfg);
    enable_json_capture_for_tests();

    // Module override allows DEBUG — must reach the event store.
    log::debug!(target: "tests.mod_override", "debug.should.pass");
    // No override — global INFO applies — must be filtered.
    log::debug!(target: "tests.other_module", "debug.must.be.filtered");

    let raw = take_json_capture();
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    let output = String::from_utf8(raw).expect("utf8");
    assert!(
        output.contains("debug.should.pass"),
        "DEBUG must pass for module with DEBUG override; got: {output}"
    );
    assert!(
        !output.contains("debug.must.be.filtered"),
        "DEBUG must be filtered for module without override; got: {output}"
    );
}

#[test]
fn logger_test_console_format_includes_timestamp_when_enabled() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let cfg = LoggingConfig {
        fmt: "console".to_string(),
        include_timestamp: true,
        ..LoggingConfig::default()
    };
    configure_logging(cfg);
    enable_console_capture_for_tests();

    let logger = get_logger(Some("tests.console_ts"));
    logger.info("console.timestamp.enabled");

    let raw = take_console_capture();
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    let line = String::from_utf8(raw).expect("utf8");
    let line = line.trim();
    assert!(
        line.starts_with("20"),
        "timestamp must appear when enabled: {line}"
    );
    assert!(
        line.contains('T'),
        "timestamp must have T separator: {line}"
    );
}

#[test]
fn logger_test_console_format_includes_context_fields() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let cfg = LoggingConfig {
        fmt: "console".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    };
    configure_logging(cfg);
    enable_console_capture_for_tests();

    let _ctx = bind_context([(
        "request_id".to_string(),
        serde_json::Value::String("ctx-abc".into()),
    )]);
    let logger = get_logger(Some("tests.console_ctx"));
    logger.info("console.context.fields");
    drop(_ctx);

    let raw = take_console_capture();
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    let line = String::from_utf8(raw).expect("utf8");
    let line = line.trim();
    assert!(
        line.contains("request_id"),
        "context key must appear in console line: {line}"
    );
    assert!(
        line.contains("ctx-abc"),
        "context value must appear in console line: {line}"
    );
}

#[test]
fn logger_test_log_trait_level_warn_filters_info() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let _ = set_as_global_logger();
    let cfg = LoggingConfig {
        level: "WARN".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    };
    configure_logging(cfg);
    enable_json_capture_for_tests();

    log::info!(target: "tests.warn_lvl", "info.filtered");
    log::warn!(target: "tests.warn_lvl", "warn.passes");
    log::error!(target: "tests.warn_lvl", "error.passes");

    let output = String::from_utf8(take_json_capture()).expect("utf8");
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    assert!(
        !output.contains("info.filtered"),
        "INFO must be filtered at WARN level"
    );
    assert!(
        output.contains("warn.passes"),
        "WARN must pass at WARN level"
    );
    assert!(
        output.contains("error.passes"),
        "ERROR must pass at WARN level"
    );
}

#[test]
fn logger_test_log_trait_level_error_filters_warn() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let _ = set_as_global_logger();
    let cfg = LoggingConfig {
        level: "ERROR".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    };
    configure_logging(cfg);
    enable_json_capture_for_tests();

    log::warn!(target: "tests.error_lvl", "warn.filtered");
    log::error!(target: "tests.error_lvl", "error.passes");

    let output = String::from_utf8(take_json_capture()).expect("utf8");
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    assert!(
        !output.contains("warn.filtered"),
        "WARN must be filtered at ERROR level"
    );
    assert!(
        output.contains("error.passes"),
        "ERROR must pass at ERROR level"
    );
}

#[test]
fn logger_test_log_trait_level_debug_allows_debug() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let _ = set_as_global_logger();
    let cfg = LoggingConfig {
        level: "DEBUG".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    };
    configure_logging(cfg);
    enable_json_capture_for_tests();

    log::debug!(target: "tests.debug_lvl", "debug.passes");
    log::info!(target: "tests.debug_lvl", "info.passes");

    let output = String::from_utf8(take_json_capture()).expect("utf8");
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    assert!(
        output.contains("debug.passes"),
        "DEBUG must pass at DEBUG level"
    );
    assert!(
        output.contains("info.passes"),
        "INFO must pass at DEBUG level"
    );
}

#[test]
fn logger_test_log_trait_level_trace_allows_trace() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let _ = set_as_global_logger();
    let cfg = LoggingConfig {
        level: "TRACE".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    };
    configure_logging(cfg);
    enable_json_capture_for_tests();

    log::trace!(target: "tests.trace_lvl", "trace.passes");
    log::debug!(target: "tests.trace_lvl", "debug.passes");

    let output = String::from_utf8(take_json_capture()).expect("utf8");
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    assert!(
        output.contains("trace.passes"),
        "TRACE must pass at TRACE level"
    );
    assert!(
        output.contains("debug.passes"),
        "DEBUG must pass at TRACE level"
    );
}

#[test]
fn logger_test_log_trait_level_aliases_warning_and_critical() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let _ = set_as_global_logger();

    // WARNING is an alias for WARN.
    let cfg = LoggingConfig {
        level: "WARNING".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    };
    configure_logging(cfg);
    enable_json_capture_for_tests();
    log::info!(target: "tests.alias_lvl", "info.filtered.warning");
    log::warn!(target: "tests.alias_lvl", "warn.passes.warning");
    let out1 = String::from_utf8(take_json_capture()).expect("utf8");
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();
    assert!(
        !out1.contains("info.filtered.warning"),
        "INFO filtered under WARNING alias"
    );
    assert!(
        out1.contains("warn.passes.warning"),
        "WARN passes under WARNING alias"
    );

    // CRITICAL is an alias for ERROR.
    let cfg2 = LoggingConfig {
        level: "CRITICAL".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    };
    configure_logging(cfg2);
    enable_json_capture_for_tests();
    log::warn!(target: "tests.alias_lvl", "warn.filtered.critical");
    log::error!(target: "tests.alias_lvl", "error.passes.critical");
    let out2 = String::from_utf8(take_json_capture()).expect("utf8");
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();
    assert!(
        !out2.contains("warn.filtered.critical"),
        "WARN filtered under CRITICAL alias"
    );
    assert!(
        out2.contains("error.passes.critical"),
        "ERROR passes under CRITICAL alias"
    );
}

#[test]
fn logger_test_emitted_logs_increments_on_log() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    use provide_telemetry::get_health_snapshot;

    let before = get_health_snapshot().emitted_logs;
    let logger = get_logger(Some("tests.health"));
    logger.info("logger.health.test");
    Logger::drain_events_for_tests();
    let after = get_health_snapshot().emitted_logs;
    assert!(
        after > before,
        "emitted_logs should increase after a log call (before={before}, after={after})"
    );
}

#[test]
fn logger_test_sampling_zero_drops_log_and_does_not_increment_emitted() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    use provide_telemetry::{get_health_snapshot, set_sampling_policy, SamplingPolicy, Signal};

    provide_telemetry::sampling::_reset_sampling_for_tests();
    provide_telemetry::health::_reset_health_for_tests();

    set_sampling_policy(
        Signal::Logs,
        SamplingPolicy {
            default_rate: 0.0,
            overrides: Default::default(),
        },
    )
    .expect("policy should set");

    let logger = get_logger(Some("tests.sampling_zero"));
    logger.info("should.be.dropped");
    Logger::drain_events_for_tests();

    let snap = get_health_snapshot();
    assert_eq!(
        snap.emitted_logs, 0,
        "emitted_logs must stay 0 when sampling rate is 0.0"
    );
    assert_eq!(
        snap.dropped_logs, 1,
        "dropped_logs must be 1 when sampling rate is 0.0"
    );

    provide_telemetry::sampling::_reset_sampling_for_tests();
    provide_telemetry::health::_reset_health_for_tests();
}

#[test]
fn logger_test_full_queue_drops_log_and_does_not_increment_emitted() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    use provide_telemetry::{
        get_health_snapshot, release, set_queue_policy, try_acquire, QueuePolicy, Signal,
    };

    provide_telemetry::backpressure::_reset_backpressure_for_tests();
    provide_telemetry::health::_reset_health_for_tests();

    // Fill the log queue completely.
    set_queue_policy(QueuePolicy {
        logs_maxsize: 1,
        traces_maxsize: 64,
        metrics_maxsize: 64,
    });
    let ticket = try_acquire(Signal::Logs).expect("first acquire must succeed");

    let logger = get_logger(Some("tests.backpressure"));
    logger.info("should.be.dropped.by.backpressure");
    Logger::drain_events_for_tests();

    let snap = get_health_snapshot();
    assert_eq!(
        snap.emitted_logs, 0,
        "emitted_logs must stay 0 when queue is full"
    );
    assert_eq!(
        snap.dropped_logs, 1,
        "dropped_logs must be 1 when queue is full"
    );

    release(ticket);
    provide_telemetry::backpressure::_reset_backpressure_for_tests();
    provide_telemetry::health::_reset_health_for_tests();
}

#[test]
fn tracer_test_sampling_zero_drops_span_but_still_calls_callback() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    use provide_telemetry::{
        get_health_snapshot, set_sampling_policy, trace, SamplingPolicy, Signal,
    };

    provide_telemetry::sampling::_reset_sampling_for_tests();
    provide_telemetry::health::_reset_health_for_tests();

    set_sampling_policy(
        Signal::Traces,
        SamplingPolicy {
            default_rate: 0.0,
            overrides: Default::default(),
        },
    )
    .expect("policy should set");

    let mut called = false;
    let result = trace("tests.trace.sampled_out", || {
        called = true;
        99_i32
    });

    assert!(
        called,
        "callback must still execute when sampling drops the span"
    );
    assert_eq!(result, 99, "callback return value must be preserved");
    let snap = get_health_snapshot();
    assert_eq!(
        snap.emitted_traces, 0,
        "emitted_traces must stay 0 when sampling rate is 0.0"
    );
    assert_eq!(
        snap.dropped_traces, 1,
        "dropped_traces must be 1 when sampling rate is 0.0"
    );

    provide_telemetry::sampling::_reset_sampling_for_tests();
    provide_telemetry::health::_reset_health_for_tests();
}

#[test]
fn tracer_test_full_queue_drops_span_but_still_calls_callback() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    use provide_telemetry::{
        get_health_snapshot, release, set_queue_policy, trace, try_acquire, QueuePolicy, Signal,
    };

    provide_telemetry::backpressure::_reset_backpressure_for_tests();
    provide_telemetry::health::_reset_health_for_tests();

    // Fill the trace queue completely.
    set_queue_policy(QueuePolicy {
        logs_maxsize: 64,
        traces_maxsize: 1,
        metrics_maxsize: 64,
    });
    let ticket = try_acquire(Signal::Traces).expect("first acquire must succeed");

    let mut called = false;
    let result = trace("tests.trace.backpressure", || {
        called = true;
        77_i32
    });

    assert!(
        called,
        "callback must still execute when backpressure drops the span"
    );
    assert_eq!(result, 77, "callback return value must be preserved");
    let snap = get_health_snapshot();
    assert_eq!(
        snap.emitted_traces, 0,
        "emitted_traces must stay 0 when queue is full"
    );
    assert_eq!(
        snap.dropped_traces, 1,
        "dropped_traces must be 1 when queue is full"
    );

    release(ticket);
    provide_telemetry::backpressure::_reset_backpressure_for_tests();
    provide_telemetry::health::_reset_health_for_tests();
}

#[test]
fn tracer_test_consent_none_skips_emitted_counter() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    use provide_telemetry::{
        get_health_snapshot, reset_consent_for_tests, set_consent_level, ConsentLevel,
    };

    reset_consent_for_tests();
    set_consent_level(ConsentLevel::None);
    let before = get_health_snapshot().emitted_traces;

    let _ = provide_telemetry::trace("test.span", || 42_i32);

    let after = get_health_snapshot().emitted_traces;
    assert_eq!(
        before, after,
        "emitted_traces should not increase when consent is None (before={before}, after={after})"
    );
    reset_consent_for_tests();
}
