// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Tests for service-identity injection and per-level sampling in the logger.

use std::collections::BTreeMap;
use std::sync::{Mutex, OnceLock};

use provide_telemetry::{
    LoggingConfig, TelemetryConfig, bind_context, enable_json_capture_for_tests, get_logger,
    reconfigure_telemetry, reset_logging_config_for_tests, shutdown_telemetry, take_json_capture,
    Logger,
};
use provide_telemetry::sampling::{SamplingPolicy, Signal, _reset_sampling_for_tests, set_sampling_policy};
use provide_telemetry::health::_reset_health_for_tests;

static LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn lock() -> &'static Mutex<()> {
    LOCK.get_or_init(|| Mutex::new(()))
}

fn setup_json_logging() {
    provide_telemetry::configure_logging(LoggingConfig {
        fmt: "json".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    });
}

fn teardown() {
    reset_logging_config_for_tests();
    shutdown_telemetry().ok();
    Logger::drain_events_for_tests();
}

#[test]
fn logger_test_json_emit_includes_service_identity_from_config() {
    let _guard = lock().lock().expect("lock poisoned");

    reconfigure_telemetry(Some(TelemetryConfig {
        service_name: "test-service".to_string(),
        environment: "test-env".to_string(),
        version: "9.9.9".to_string(),
        ..TelemetryConfig::default()
    }))
    .expect("reconfigure should succeed");

    setup_json_logging();
    enable_json_capture_for_tests();

    get_logger(Some("tests.svc")).info("identity.check");

    let raw = take_json_capture();
    teardown();

    let parsed: serde_json::Value =
        serde_json::from_str(String::from_utf8(raw).expect("utf8").trim()).expect("valid JSON");
    assert_eq!(parsed["service"], "test-service", "service must come from config");
    assert_eq!(parsed["env"], "test-env", "env must come from config");
    assert_eq!(parsed["version"], "9.9.9", "version must come from config");
}

#[test]
fn logger_test_context_bound_service_takes_precedence_over_config() {
    let _guard = lock().lock().expect("lock poisoned");

    reconfigure_telemetry(Some(TelemetryConfig {
        service_name: "config-service".to_string(),
        ..TelemetryConfig::default()
    }))
    .expect("reconfigure should succeed");

    setup_json_logging();
    enable_json_capture_for_tests();

    let _ctx = bind_context([("service", serde_json::json!("context-service"))]);
    get_logger(Some("tests.ctx")).info("context.precedence.check");

    let raw = take_json_capture();
    teardown();

    let parsed: serde_json::Value =
        serde_json::from_str(String::from_utf8(raw).expect("utf8").trim()).expect("valid JSON");
    assert_eq!(
        parsed["service"], "context-service",
        "context-bound service must take precedence over config"
    );
}

#[test]
fn logger_test_per_message_sampling_override_is_applied() {
    let _guard = lock().lock().expect("lock poisoned");

    _reset_sampling_for_tests();
    _reset_health_for_tests();

    // "drop.this.message" → always drop; all other messages → always keep (default_rate 1.0)
    let mut overrides = BTreeMap::new();
    overrides.insert("drop.this.message".to_string(), 0.0_f64);
    set_sampling_policy(Signal::Logs, SamplingPolicy { default_rate: 1.0, overrides })
        .expect("set_sampling_policy should succeed");

    let logger = get_logger(Some("tests.per_message"));

    let before = provide_telemetry::get_health_snapshot().emitted_logs;
    logger.info("drop.this.message");
    assert_eq!(
        provide_telemetry::get_health_snapshot().emitted_logs, before,
        "message must be dropped when override rate is 0.0"
    );

    let before = provide_telemetry::get_health_snapshot().emitted_logs;
    logger.info("other.message");
    assert_eq!(
        provide_telemetry::get_health_snapshot().emitted_logs, before + 1,
        "other messages must pass when default_rate is 1.0"
    );

    _reset_sampling_for_tests();
    _reset_health_for_tests();
    Logger::drain_events_for_tests();
}
