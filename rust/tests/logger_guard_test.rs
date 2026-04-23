// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use std::collections::BTreeMap;
use std::sync::{Mutex, OnceLock};

use provide_telemetry::testing::{acquire_test_state_lock, reset_telemetry_state};
use provide_telemetry::{
    bind_context, bind_session_context, configure_logging, event, get_logger,
    reconfigure_telemetry, release, reset_logging_config_for_tests, set_queue_policy,
    set_sampling_policy, set_trace_context, try_acquire, ExporterPolicyConfig, Logger,
    LoggingConfig, QueuePolicy, SamplingPolicy, SecurityConfig, Signal, TelemetryConfig,
};
#[cfg(feature = "governance")]
use provide_telemetry::{reset_consent_for_tests, set_consent_level, ConsentLevel};
use serde_json::json;

static LOGGER_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn logger_lock() -> &'static Mutex<()> {
    LOGGER_LOCK.get_or_init(|| Mutex::new(()))
}

fn acquire_logger_lock() -> std::sync::MutexGuard<'static, ()> {
    logger_lock()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

fn reset_logger_harness() {
    reset_telemetry_state();
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();
    for key in [
        "PROVIDE_TELEMETRY_SERVICE_NAME",
        "PROVIDE_TELEMETRY_ENV",
        "PROVIDE_TELEMETRY_VERSION",
    ] {
        std::env::remove_var(key);
    }
}

#[test]
fn logger_fields_and_event_helpers_cover_threshold_sampling_and_queue_guards() {
    let _state = acquire_test_state_lock();
    let _logger = acquire_logger_lock();

    reset_logger_harness();
    configure_logging(LoggingConfig {
        level: "ERROR".to_string(),
        ..LoggingConfig::default()
    });
    let logger = get_logger(Some("tests.logger.guards"));
    let mut extra = BTreeMap::new();
    extra.insert("step".to_string(), json!("threshold"));
    let ev = event(&["auth", "login", "account", "success"]).expect("event should build");
    logger.info_fields("below.threshold", &extra);
    logger.info_event(&ev);
    assert!(Logger::drain_events_for_tests().is_empty());

    reset_logger_harness();
    configure_logging(LoggingConfig {
        level: "TRACE".to_string(),
        ..LoggingConfig::default()
    });
    set_sampling_policy(
        Signal::Logs,
        SamplingPolicy {
            default_rate: 0.0,
            overrides: BTreeMap::new(),
        },
    )
    .expect("sampling policy should set");
    let logger = get_logger(Some("tests.logger.guards"));
    logger.error_fields("sampled.out", &extra);
    logger.error_event(&ev);
    assert!(Logger::drain_events_for_tests().is_empty());

    reset_logger_harness();
    configure_logging(LoggingConfig {
        level: "TRACE".to_string(),
        ..LoggingConfig::default()
    });
    set_queue_policy(QueuePolicy {
        logs_maxsize: 1,
        traces_maxsize: 0,
        metrics_maxsize: 0,
    });
    let held = try_acquire(Signal::Logs).expect("first log ticket should succeed");
    let logger = get_logger(Some("tests.logger.guards"));
    logger.error_fields("queue.blocked", &extra);
    logger.error_event(&ev);
    release(held);
    assert!(Logger::drain_events_for_tests().is_empty());
}

#[test]
fn logger_processors_cover_resource_identity_schema_and_non_string_context_paths() {
    let _state = acquire_test_state_lock();
    let _logger = acquire_logger_lock();

    reset_logger_harness();
    reconfigure_telemetry(Some(TelemetryConfig {
        event_schema: provide_telemetry::EventSchemaConfig {
            strict_event_name: false,
            required_keys: vec!["request_id".to_string()],
        },
        security: SecurityConfig {
            max_attr_value_length: 64,
            max_attr_count: 13,
            max_nesting_depth: 8,
        },
        exporter: ExporterPolicyConfig::default(),
        ..TelemetryConfig::default()
    }))
    .expect("runtime config should install");
    configure_logging(LoggingConfig {
        level: "TRACE".to_string(),
        ..LoggingConfig::default()
    });

    let _context = bind_context([("alpha", json!(1)), ("clean", json!("ok"))]);
    let _session = bind_session_context("session-1");
    let _trace = set_trace_context(
        Some("0123456789abcdef0123456789abcdef".to_string()),
        Some("0123456789abcdef".to_string()),
    );
    let logger = get_logger(Some("tests.logger.processors"));

    let resource_event =
        event(&["auth", "login", "account", "success"]).expect("resource event should build");
    logger.info_event(&resource_event);

    let mut error_fields = BTreeMap::new();
    error_fields.insert("error".to_string(), json!("BoomError"));
    error_fields.insert("stacktrace".to_string(), json!("stack-value"));
    error_fields.insert("count".to_string(), json!(3));
    logger.error_fields("auth.login.failed", &error_fields);

    logger.info("auth.login.success");

    let events = Logger::drain_events_for_tests();
    assert_eq!(events.len(), 3);

    assert_eq!(events[0].context.get("resource"), Some(&json!("account")));
    assert_eq!(
        events[0].context.get("session_id"),
        Some(&json!("session-1"))
    );
    assert_eq!(events[0].context.get("alpha"), Some(&json!(1)));

    assert_eq!(events[1].context.get("count"), Some(&json!(3)));
    assert_eq!(
        events[1].context.get("stacktrace"),
        Some(&json!("stack-value"))
    );
    assert!(events[1].context.contains_key("error_fingerprint"));

    assert!(
        events[2].context.contains_key("_schema_error"),
        "missing required keys should annotate the emitted event"
    );
    assert_eq!(events[2].context.get("clean"), Some(&json!("ok")));
}

#[test]
fn logger_without_runtime_or_env_identity_omits_service_fields() {
    let _state = acquire_test_state_lock();
    let _logger = acquire_logger_lock();

    reset_logger_harness();
    configure_logging(LoggingConfig {
        level: "TRACE".to_string(),
        ..LoggingConfig::default()
    });
    std::env::set_var("PROVIDE_LOG_INCLUDE_TIMESTAMP", "not-a-bool");

    let logger = get_logger(Some("tests.logger.identityless"));
    logger.info("identityless.message");

    let events = Logger::drain_events_for_tests();
    std::env::remove_var("PROVIDE_LOG_INCLUDE_TIMESTAMP");
    assert_eq!(events.len(), 1);
    assert!(!events[0].context.contains_key("service"));
    assert!(!events[0].context.contains_key("env"));
    assert!(!events[0].context.contains_key("version"));
}

#[test]
fn logger_public_paths_cover_parse_failure_empty_fields_and_fallback_buffer_cap() {
    let _state = acquire_test_state_lock();
    let _logger = acquire_logger_lock();

    reset_logger_harness();
    std::env::set_var("PROVIDE_LOG_INCLUDE_TIMESTAMP", "not-a-bool");

    let logger = get_logger(Some("tests.logger.parse"));
    logger.info_fields("parse.default.path", &BTreeMap::new());

    std::env::remove_var("PROVIDE_LOG_INCLUDE_TIMESTAMP");
    let events = Logger::drain_events_for_tests();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].message, "parse.default.path");

    reset_logger_harness();
    configure_logging(LoggingConfig {
        level: "TRACE".to_string(),
        ..LoggingConfig::default()
    });
    let logger = get_logger(Some("tests.logger.buffer"));
    for idx in 0..1005 {
        logger.info(&format!("buffer.message.{idx}"));
    }

    let buffered = Logger::drain_events_for_tests();
    assert_eq!(buffered.len(), 1000, "fallback buffer must stay capped");
}

#[cfg(feature = "governance")]
#[test]
fn logger_public_paths_cover_plain_log_guards_and_log_trait_variants() {
    let _state = acquire_test_state_lock();
    let _logger = acquire_logger_lock();

    reset_logger_harness();
    configure_logging(LoggingConfig {
        level: "ERROR".to_string(),
        ..LoggingConfig::default()
    });
    let logger = get_logger(Some("tests.logger.guards"));
    logger.info("below.threshold.plain");
    assert!(Logger::drain_events_for_tests().is_empty());

    reset_logger_harness();
    configure_logging(LoggingConfig {
        level: "TRACE".to_string(),
        ..LoggingConfig::default()
    });
    reset_consent_for_tests();
    set_consent_level(ConsentLevel::None);
    let logger = get_logger(Some("tests.logger.guards"));
    logger.error("blocked.by.consent");
    assert!(Logger::drain_events_for_tests().is_empty());
    reset_consent_for_tests();

    reset_logger_harness();
    configure_logging(LoggingConfig {
        level: "TRACE".to_string(),
        ..LoggingConfig::default()
    });
    set_sampling_policy(
        Signal::Logs,
        SamplingPolicy {
            default_rate: 0.0,
            overrides: BTreeMap::new(),
        },
    )
    .expect("sampling policy should set");
    let logger = get_logger(Some("tests.logger.guards"));
    logger.error("sampled.out.plain");
    assert!(Logger::drain_events_for_tests().is_empty());

    reset_logger_harness();
    configure_logging(LoggingConfig {
        level: "TRACE".to_string(),
        ..LoggingConfig::default()
    });
    set_queue_policy(QueuePolicy {
        logs_maxsize: 1,
        traces_maxsize: 0,
        metrics_maxsize: 0,
    });
    let held = try_acquire(Signal::Logs).expect("first log ticket should succeed");
    let logger = get_logger(Some("tests.logger.guards"));
    logger.error("queue.blocked.plain");
    release(held);
    assert!(Logger::drain_events_for_tests().is_empty());

    reset_logger_harness();
    configure_logging(LoggingConfig {
        level: "WARN".to_string(),
        ..LoggingConfig::default()
    });
    let logger = get_logger(Some("tests.logger.logtrait"));
    let filtered = log::Record::builder()
        .args(format_args!("filtered.debug"))
        .level(log::Level::Debug)
        .target("tests.logger.logtrait")
        .build();
    log::Log::log(&logger, &filtered);
    assert!(Logger::drain_events_for_tests().is_empty());

    configure_logging(LoggingConfig {
        level: "TRACE".to_string(),
        ..LoggingConfig::default()
    });
    for (level, message) in [
        (log::Level::Error, "trait.error"),
        (log::Level::Info, "trait.info"),
        (log::Level::Debug, "trait.debug"),
        (log::Level::Trace, "trait.trace"),
    ] {
        let args = format_args!("{message}");
        let record = log::Record::builder()
            .args(args)
            .level(level)
            .target("tests.logger.logtrait")
            .build();
        log::Log::log(&logger, &record);
    }

    let events = Logger::drain_events_for_tests();
    assert_eq!(events.len(), 4);
    assert_eq!(events[0].level, "ERROR");
    assert_eq!(events[1].level, "INFO");
    assert_eq!(events[2].level, "DEBUG");
    assert_eq!(events[3].level, "TRACE");
}

#[test]
fn logger_public_paths_cover_secret_message_truncation_strict_schema_and_empty_target() {
    let _state = acquire_test_state_lock();
    let _logger = acquire_logger_lock();

    reset_logger_harness();
    reconfigure_telemetry(Some(TelemetryConfig {
        strict_schema: true,
        security: SecurityConfig {
            max_attr_value_length: 5,
            max_attr_count: 8,
            max_nesting_depth: 8,
        },
        ..TelemetryConfig::default()
    }))
    .expect("runtime config should install");
    configure_logging(LoggingConfig {
        level: "TRACE".to_string(),
        ..LoggingConfig::default()
    });

    let logger = get_logger(Some(""));
    logger.info("token AKIAIOSFODNN7EXAMPLE leaked");

    let mut fields = BTreeMap::new();
    fields.insert("alpha".to_string(), json!("abcdefghi"));
    fields.insert("beta".to_string(), json!(format!("line{}break\tok", '\0')));
    fields.insert("gamma".to_string(), json!("keep"));
    fields.insert("delta".to_string(), json!("drop"));
    logger.info_fields("Bad-Event.Name", &fields);

    let events = Logger::drain_events_for_tests();
    assert_eq!(events.len(), 2);

    assert_eq!(events[0].message, "***");
    assert!(!events[0].context.contains_key("logger_name"));
    assert!(events[0].context.contains_key("_schema_error"));

    assert_eq!(events[1].context.get("logger_name"), None);
    assert_eq!(events[1].context.get("alpha"), Some(&json!("abcde...")));
    assert_eq!(events[1].context.get("beta"), Some(&json!("line...")));
    assert!(events[1].context.contains_key("_schema_error"));
}
