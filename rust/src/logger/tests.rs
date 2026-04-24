// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

//! Tests for module-level logger helpers. Split out of `logger/mod.rs` so the
//! parent stays under the 500-LOC ceiling.

use super::*;
use std::collections::{BTreeMap, HashMap};

use serde_json::json;

use crate::TelemetryConfig;
use crate::runtime::set_active_config;
use crate::schema::event;
use crate::testing::{acquire_test_state_lock, reset_telemetry_state};
use crate::tracer::set_trace_context;
#[cfg(feature = "governance")]
use crate::{ConsentLevel, reset_consent_for_tests, set_consent_level};

fn cfg_with_module_level(module: &str, level: &str) -> crate::config::LoggingConfig {
    let mut module_levels = HashMap::new();
    module_levels.insert(module.to_string(), level.to_string());
    crate::config::LoggingConfig {
        level: "INFO".to_string(),
        module_levels,
        ..crate::config::LoggingConfig::default()
    }
}

fn trace_json_config() -> crate::config::LoggingConfig {
    crate::config::LoggingConfig {
        level: "TRACE".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..crate::config::LoggingConfig::default()
    }
}

fn reset_logger_state() {
    reset_telemetry_state();
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();
    let _ = take_json_capture();
    let _ = take_console_capture();
    for key in [
        "PROVIDE_LOG_LEVEL",
        "PROVIDE_LOG_FORMAT",
        "PROVIDE_LOG_INCLUDE_TIMESTAMP",
        "PROVIDE_LOG_MODULE_LEVELS",
    ] {
        std::env::remove_var(key);
    }
    #[cfg(feature = "governance")]
    reset_consent_for_tests();
}

fn enable_test_capture() {
    enable_json_capture_for_tests();
    enable_console_capture_for_tests();
}

// ── Issue #2: dot-hierarchy prefix matching ───────────────────────────────

#[test]
fn effective_level_does_not_match_partial_string() {
    // "foobar" must NOT match prefix "foo" — no dot separator between them
    let cfg = cfg_with_module_level("foo", "DEBUG");
    // INFO = 2, so global threshold applies
    assert_eq!(
        effective_level_threshold("foobar", &cfg),
        2,
        "foobar must not match prefix foo (no dot separator)"
    );
}

#[test]
fn effective_level_matches_dot_separated_child() {
    // "foo.bar" starts with "foo." → should pick up DEBUG override
    let cfg = cfg_with_module_level("foo", "DEBUG");
    assert_eq!(
        effective_level_threshold("foo.bar", &cfg),
        1,
        "foo.bar must match prefix foo via dot separator"
    );
}

#[test]
fn effective_level_matches_exact_module_name() {
    // "foo" == "foo" → exact match → DEBUG override applies
    let cfg = cfg_with_module_level("foo", "DEBUG");
    assert_eq!(
        effective_level_threshold("foo", &cfg),
        1,
        "exact name must match"
    );
}

#[test]
fn effective_level_empty_prefix_matches_everything() {
    // empty prefix is a catch-all
    let cfg = cfg_with_module_level("", "DEBUG");
    assert_eq!(
        effective_level_threshold("anything.at.all", &cfg),
        1,
        "empty prefix must match any target"
    );
}

#[test]
fn effective_level_longest_prefix_wins() {
    let mut module_levels = HashMap::new();
    module_levels.insert("foo".to_string(), "WARN".to_string());
    module_levels.insert("foo.bar".to_string(), "DEBUG".to_string());
    let cfg = crate::config::LoggingConfig {
        level: "INFO".to_string(),
        module_levels,
        ..crate::config::LoggingConfig::default()
    };
    // "foo.bar.baz" matches both "foo" and "foo.bar"; "foo.bar" is longer → DEBUG wins
    assert_eq!(
        effective_level_threshold("foo.bar.baz", &cfg),
        1,
        "longer prefix must win over shorter"
    );
}

#[test]
fn active_logging_config_prefers_override_then_runtime_then_env() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();

    std::env::set_var("PROVIDE_LOG_FORMAT", "json");
    std::env::set_var("PROVIDE_LOG_INCLUDE_TIMESTAMP", "false");
    assert_eq!(active_logging_config().fmt, "json");
    assert!(!active_logging_config().include_timestamp);

    set_active_config(Some(TelemetryConfig {
        logging: crate::config::LoggingConfig {
            level: "WARN".to_string(),
            fmt: "console".to_string(),
            include_timestamp: false,
            ..crate::config::LoggingConfig::default()
        },
        ..TelemetryConfig::default()
    }));
    assert_eq!(active_logging_config().level, "WARN");
    assert_eq!(active_logging_config().fmt, "console");

    configure_logging(trace_json_config());
    assert_eq!(active_logging_config(), trace_json_config());
}

#[test]
fn active_logging_config_falls_back_to_defaults_when_env_parse_fails() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();

    std::env::set_var("PROVIDE_LOG_INCLUDE_TIMESTAMP", "not-a-bool");

    assert_eq!(
        active_logging_config(),
        crate::config::LoggingConfig::default()
    );

    std::env::remove_var("PROVIDE_LOG_INCLUDE_TIMESTAMP");
}

#[test]
fn reset_logging_config_for_tests_clears_programmatic_override() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();

    std::env::set_var("PROVIDE_LOG_INCLUDE_TIMESTAMP", "not-a-bool");

    let override_cfg = trace_json_config();
    configure_logging(override_cfg.clone());
    assert_eq!(active_logging_config(), override_cfg);

    reset_logging_config_for_tests();
    assert_eq!(
        active_logging_config(),
        crate::config::LoggingConfig::default()
    );

    std::env::remove_var("PROVIDE_LOG_INCLUDE_TIMESTAMP");
}

#[test]
fn new_event_injects_runtime_identity_context_and_trace() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();

    set_active_config(Some(TelemetryConfig {
        service_name: "svc".to_string(),
        environment: "stage".to_string(),
        version: "1.2.3".to_string(),
        ..TelemetryConfig::default()
    }));
    let _context = crate::context::bind_context([("request_id", json!("req-1"))]);
    let _trace = set_trace_context(
        Some("0123456789abcdef0123456789abcdef".to_string()),
        Some("0123456789abcdef".to_string()),
    );

    let event = new_event("tests.identity", "INFO", "identity.check");

    assert_eq!(event.target, "tests.identity");
    assert_eq!(event.level, "INFO");
    assert_eq!(event.message, "identity.check");
    assert_eq!(event.context.get("request_id"), Some(&json!("req-1")));
    assert_eq!(event.context.get("service"), Some(&json!("svc")));
    assert_eq!(event.context.get("env"), Some(&json!("stage")));
    assert_eq!(event.context.get("version"), Some(&json!("1.2.3")));
    assert_eq!(
        event.trace_id.as_deref(),
        Some("0123456789abcdef0123456789abcdef")
    );
    assert_eq!(event.span_id.as_deref(), Some("0123456789abcdef"));
    assert_eq!(event.event_metadata, None);
}

#[test]
fn new_event_skips_identity_when_runtime_and_env_config_are_unavailable() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    std::env::set_var("PROVIDE_LOG_PII_MAX_DEPTH", "-1");

    let event = new_event("tests.identity", "INFO", "identity.missing");

    assert_eq!(event.context.get("service"), None);
    assert_eq!(event.context.get("env"), None);
    assert_eq!(event.context.get("version"), None);

    std::env::remove_var("PROVIDE_LOG_PII_MAX_DEPTH");
}

#[test]
fn inject_runtime_identity_fields_is_a_noop_without_runtime_or_valid_env() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    std::env::set_var("PROVIDE_LOG_PII_MAX_DEPTH", "-1");

    let mut context = BTreeMap::new();
    inject_runtime_identity_fields(&mut context);

    assert!(context.is_empty());
    std::env::remove_var("PROVIDE_LOG_PII_MAX_DEPTH");
}

#[test]
fn log_event_helpers_cover_threshold_fields_and_event_metadata() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    configure_logging(crate::config::LoggingConfig {
        level: "INFO".to_string(),
        ..trace_json_config()
    });
    enable_test_capture();

    let before = crate::health::get_health_snapshot();
    log_event("DEBUG", "tests.filtered", "filtered.out");
    assert!(Logger::drain_events_for_tests().is_empty());
    assert_eq!(
        crate::health::get_health_snapshot().emitted_logs,
        before.emitted_logs
    );

    configure_logging(crate::config::LoggingConfig {
        level: "INFO".to_string(),
        ..trace_json_config()
    });
    let mut extra = BTreeMap::new();
    extra.insert("step".to_string(), json!("parse"));
    log_event_with_fields("INFO", "tests.fields", "fields.ok", &extra);

    let ev = event(&["auth", "login", "success"]).expect("event should build");
    log_event_with_event("ERROR", "tests.event", &ev);

    let events = Logger::drain_events_for_tests();
    assert_eq!(events.len(), 2);
    assert_eq!(events[0].context.get("step"), Some(&json!("parse")));
    assert_eq!(
        events[1].event_metadata,
        Some(EventMetadata {
            domain: "auth".to_string(),
            action: "login".to_string(),
            resource: None,
            status: "success".to_string(),
        })
    );
}

#[cfg(feature = "governance")]
#[test]
fn log_event_helpers_respect_consent_gate() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    configure_logging(trace_json_config());
    enable_test_capture();
    set_consent_level(ConsentLevel::None);
    let before = crate::health::get_health_snapshot();

    log_event("ERROR", "tests.consent", "blocked.by.consent");
    log_event_with_fields("ERROR", "tests.consent", "blocked.fields", &BTreeMap::new());
    let ev = event(&["auth", "login", "denied"]).expect("event should build");
    log_event_with_event("ERROR", "tests.consent", &ev);

    assert!(Logger::drain_events_for_tests().is_empty());
    assert_eq!(crate::health::get_health_snapshot(), before);
}

#[test]
fn wrapper_loggers_cover_public_methods_and_buffering() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    configure_logging(trace_json_config());
    enable_test_capture();

    assert_eq!(logger.target(), "provide.telemetry");
    let test_logger = get_logger(Some("tests.named"));
    assert_eq!(test_logger.target(), "tests.named");

    let mut fields = BTreeMap::new();
    fields.insert("key".to_string(), json!("value"));
    let ev = event(&["orders", "create", "ok"]).expect("event should build");

    test_logger.debug("debug.message");
    test_logger.info("info.message");
    test_logger.warn("warn.message");
    test_logger.error("error.message");
    test_logger.log("TRACE", "trace.message");
    test_logger.debug_fields("debug.fields", &fields);
    test_logger.info_fields("info.fields", &fields);
    test_logger.warn_fields("warn.fields", &fields);
    test_logger.error_fields("error.fields", &fields);
    test_logger.debug_event(&ev);
    test_logger.info_event(&ev);
    test_logger.warn_event(&ev);
    test_logger.error_event(&ev);

    let drained = Logger::drain_events_for_tests();
    assert_eq!(drained.len(), 13);
    assert_eq!(drained[0].target, "tests.named");
    assert_eq!(drained[0].level, "DEBUG");
    assert_eq!(drained[4].level, "TRACE");
    assert_eq!(drained[5].context.get("key"), Some(&json!("value")));
    assert_eq!(
        drained[12]
            .event_metadata
            .as_ref()
            .map(|m| m.status.as_str()),
        Some("ok")
    );

    let null = null_logger(Some("tests.null"));
    assert_eq!(null.target(), "tests.null");
    null.debug("ignored");
    null.info("ignored");
    null.warn("ignored");
    null.error("ignored");
    assert!(Logger::drain_events_for_tests().is_empty());

    let buffered = buffer_logger(Some("tests.buffer"));
    assert_eq!(buffered.target(), "tests.buffer");
    buffered.debug("buffer.debug");
    buffered.info("buffer.info");
    buffered.warn("buffer.warn");
    buffered.error("buffer.error");
    buffered.log("TRACE", "buffer.trace");
    let buffered_events = buffered.drain();
    assert_eq!(buffered_events.len(), 5);
    assert_eq!(buffered_events[0].target, "tests.buffer");
    assert_eq!(buffered_events[4].level, "TRACE");
}

#[test]
fn buffer_logger_respects_threshold_and_global_log_trait_covers_enabled_and_flush() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    configure_logging(crate::config::LoggingConfig {
        level: "WARN".to_string(),
        ..trace_json_config()
    });
    enable_test_capture();

    let buffered = BufferLogger::new(Some("tests.threshold"));
    buffered.debug("filtered.debug");
    buffered.info("filtered.info");
    buffered.warn("kept.warn");
    buffered.error("kept.error");
    let buffered_events = buffered.drain();
    assert_eq!(buffered_events.len(), 2);
    assert_eq!(buffered_events[0].level, "WARN");
    assert_eq!(buffered_events[1].level, "ERROR");

    let facade = Logger::new(Some("tests.trait"));
    let debug_meta = log::Metadata::builder()
        .level(log::Level::Debug)
        .target("tests.trait")
        .build();
    let error_meta = log::Metadata::builder()
        .level(log::Level::Error)
        .target("tests.trait")
        .build();
    assert!(!log::Log::enabled(&facade, &debug_meta));
    assert!(log::Log::enabled(&facade, &error_meta));

    configure_logging(trace_json_config());
    enable_test_capture();
    let trace_record = log::Record::builder()
        .args(format_args!("trace.record"))
        .level(log::Level::Trace)
        .target("tests.trait")
        .build();
    let warn_record = log::Record::builder()
        .args(format_args!("warn.record"))
        .level(log::Level::Warn)
        .target("tests.trait")
        .build();
    log::Log::log(&facade, &trace_record);
    log::Log::log(&facade, &warn_record);
    log::Log::flush(&facade);

    let events = Logger::drain_events_for_tests();
    assert_eq!(events.len(), 2);
    assert_eq!(events[0].level, "TRACE");
    assert_eq!(events[1].level, "WARN");
}

#[test]
fn emit_event_caps_the_fallback_event_buffer() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    configure_logging(trace_json_config());
    enable_test_capture();

    for idx in 0..(MAX_FALLBACK_EVENTS + 2) {
        emit_event(LogEvent {
            level: "INFO".to_string(),
            target: "tests.cap".to_string(),
            message: format!("cap.{idx}"),
            context: BTreeMap::new(),
            trace_id: None,
            span_id: None,
            event_metadata: None,
        });
    }

    let events = Logger::drain_events_for_tests();
    assert_eq!(events.len(), MAX_FALLBACK_EVENTS);
    assert_eq!(
        events.first().map(|event| event.message.as_str()),
        Some("cap.0")
    );
    assert_eq!(
        events.last().map(|event| event.message.as_str()),
        Some("cap.999")
    );
}

#[test]
fn log_fields_with_empty_map_still_emits() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    configure_logging(trace_json_config());
    enable_test_capture();

    let empty_fields_logger = Logger::new(Some("tests.empty.fields"));
    let fields = BTreeMap::new();
    empty_fields_logger.log_fields("INFO", "empty.fields", &fields);

    let events = Logger::drain_events_for_tests();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].message, "empty.fields");
}

#[test]
fn set_as_global_logger_covers_success_and_already_installed_error() {
    let _guard = acquire_test_state_lock();

    assert!(set_as_global_logger().is_ok());
    assert!(set_as_global_logger().is_err());
}
