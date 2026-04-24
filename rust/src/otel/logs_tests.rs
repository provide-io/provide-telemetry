// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use super::*;
use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::Duration;

use opentelemetry::InstrumentationScope;
use opentelemetry_sdk::error::{OTelSdkError, OTelSdkResult};
use opentelemetry_sdk::logs::{LogProcessor, SdkLogRecord, SdkLoggerProvider};

use crate::testing::{acquire_test_state_lock, reset_telemetry_state};

fn test_config() -> TelemetryConfig {
    TelemetryConfig {
        service_name: "test".to_string(),
        ..TelemetryConfig::default()
    }
}

fn reset_logs_test_state() -> std::sync::MutexGuard<'static, ()> {
    let guard = acquire_test_state_lock();
    reset_telemetry_state();
    shutdown_logger_provider();
    guard
}

#[test]
fn shutdown_without_install_is_a_noop() {
    let _guard = reset_logs_test_state();
    shutdown_logger_provider();
}

#[test]
fn install_without_endpoint_returns_false_and_leaves_provider_uninstalled() {
    let _guard = reset_logs_test_state();
    let cfg = test_config();
    let resource = super::super::resource::build_resource(&cfg);

    let installed = install_logger_provider(&cfg, resource).expect("no endpoint is not error");

    assert!(!installed);
    assert!(!logger_provider_installed());
}

#[test]
fn build_exporter_rejects_invalid_endpoint_scheme() {
    let _guard = reset_logs_test_state();
    let mut cfg = test_config();
    cfg.logging.otlp_endpoint = Some("ftp://host:4318".to_string());
    let err = build_exporter(&cfg).expect_err("ftp scheme must be rejected");
    assert!(
        err.message.contains("scheme"),
        "error must mention bad scheme: {}",
        err.message
    );
}

#[test]
fn build_exporter_rejects_invalid_protocol() {
    let _guard = reset_logs_test_state();
    let mut cfg = test_config();
    cfg.logging.otlp_protocol = "kafka".to_string();

    let err = build_exporter(&cfg).expect_err("unknown OTLP protocol must fail");
    assert!(err.message.contains("protocol"));
}

#[test]
fn install_with_bad_endpoint_fails_closed_by_default() {
    let _guard = reset_logs_test_state();
    let mut cfg = test_config();
    cfg.logging.otlp_endpoint = Some("ftp://host:4318".to_string());
    cfg.exporter.logs_fail_open = false;
    let resource = super::super::resource::build_resource(&cfg);
    let result = install_logger_provider(&cfg, resource);
    assert!(
        result.is_err(),
        "bad endpoint must return Err when fail_open=false"
    );
    let msg = result.unwrap_err().message;
    assert!(
        msg.contains("scheme"),
        "error must mention bad scheme: {msg}"
    );
}

#[test]
fn install_with_bad_endpoint_succeeds_when_fail_open() {
    let _guard = reset_logs_test_state();
    let mut cfg = test_config();
    cfg.logging.otlp_endpoint = Some("ftp://host:4318".to_string());
    cfg.exporter.logs_fail_open = true;
    let resource = super::super::resource::build_resource(&cfg);
    install_logger_provider(&cfg, resource).expect("fail_open must absorb validation error");
}

#[test]
fn install_with_unreachable_endpoint_succeeds_under_fail_open() {
    let _guard = reset_logs_test_state();
    let mut cfg = test_config();
    cfg.logging.otlp_endpoint = Some("http://127.0.0.1:1/never/v1/logs".to_string());
    cfg.exporter.logs_fail_open = true;
    let resource = super::super::resource::build_resource(&cfg);
    install_logger_provider(&cfg, resource).expect("install must succeed under fail_open");

    emit_log(&LogEvent {
        level: "INFO".to_string(),
        target: "tests.otel.logs".to_string(),
        message: "test message".to_string(),
        context: BTreeMap::new(),
        trace_id: None,
        span_id: None,
        event_metadata: None,
    });
    shutdown_logger_provider();
}

#[test]
fn build_exporter_accepts_headers_and_http_json_protocol() {
    let _guard = reset_logs_test_state();
    let mut cfg = test_config();
    cfg.logging.otlp_endpoint = Some("http://127.0.0.1:4318/v1/logs".to_string());
    cfg.logging.otlp_protocol = "http/json".to_string();
    cfg.logging
        .otlp_headers
        .insert("authorization".to_string(), "Bearer token".to_string());

    build_exporter(&cfg).expect("valid endpoint, headers, and protocol should build");
}

#[test]
fn build_exporter_accepts_http_defaults_without_endpoint_or_headers() {
    let _guard = reset_logs_test_state();
    let mut cfg = test_config();
    cfg.logging.otlp_protocol = "http/protobuf".to_string();
    cfg.logging.otlp_endpoint = None;
    cfg.logging.otlp_headers.clear();

    build_exporter(&cfg).expect("http defaults should build without explicit endpoint");
}

#[cfg(feature = "otel-grpc")]
#[tokio::test(flavor = "current_thread")]
async fn build_exporter_accepts_grpc_protocol_and_metadata() {
    let _guard = reset_logs_test_state();
    let mut cfg = test_config();
    cfg.logging.otlp_endpoint = Some("http://127.0.0.1:4317".to_string());
    cfg.logging.otlp_protocol = "grpc".to_string();
    cfg.logging
        .otlp_headers
        .insert("authorization".to_string(), "Bearer token".to_string());

    build_exporter(&cfg).expect("valid grpc endpoint and metadata should build");
}

#[cfg(feature = "otel-grpc")]
#[tokio::test(flavor = "current_thread")]
async fn build_exporter_accepts_grpc_defaults_without_endpoint_or_headers() {
    let _guard = reset_logs_test_state();
    let mut cfg = test_config();
    cfg.logging.otlp_protocol = "grpc".to_string();

    build_exporter(&cfg).expect("grpc defaults should build under a tokio runtime");
}

#[cfg(feature = "otel-grpc")]
#[test]
fn build_exporter_rejects_invalid_grpc_header_value() {
    let _guard = reset_logs_test_state();
    let mut cfg = test_config();
    cfg.logging.otlp_endpoint = Some("http://127.0.0.1:4317".to_string());
    cfg.logging.otlp_protocol = "grpc".to_string();
    cfg.logging
        .otlp_headers
        .insert("authorization".to_string(), "bad\nvalue".to_string());

    let err = build_exporter(&cfg).expect_err("invalid metadata must fail grpc exporter build");
    assert!(err.message.contains("build failed") || err.message.contains("invalid OTLP header"));
}

#[cfg(feature = "otel-grpc")]
#[test]
fn build_exporter_rejects_invalid_grpc_endpoint_scheme() {
    let _guard = reset_logs_test_state();
    let mut cfg = test_config();
    cfg.logging.otlp_endpoint = Some("ftp://127.0.0.1:4317".to_string());
    cfg.logging.otlp_protocol = "grpc".to_string();

    let err = build_exporter(&cfg).expect_err("invalid grpc endpoint must fail");
    assert!(err.message.contains("scheme"));
}

#[test]
fn level_to_severity_covers_all_defined_levels() {
    let _guard = reset_logs_test_state();
    for (lvl, expect_text) in [
        ("TRACE", "TRACE"),
        ("trace", "TRACE"),
        ("DEBUG", "DEBUG"),
        ("debug", "DEBUG"),
        ("INFO", "INFO"),
        ("info", "INFO"),
        ("WARN", "WARN"),
        ("WARNING", "WARN"),
        ("warn", "WARN"),
        ("warning", "WARN"),
        ("ERROR", "ERROR"),
        ("error", "ERROR"),
        ("CRITICAL", "FATAL"),
        ("FATAL", "FATAL"),
        ("critical", "FATAL"),
        ("fatal", "FATAL"),
        ("unknown", "INFO"),
    ] {
        let (_, text) = level_to_severity(lvl);
        assert_eq!(text, expect_text, "level {lvl} should map to {expect_text}");
    }
}

#[test]
fn helper_converters_cover_scalar_complex_and_invalid_hex_inputs() {
    let _guard = reset_logs_test_state();
    assert!(matches!(json_to_any(&Value::Null), AnyValue::String(_)));
    assert!(matches!(
        json_to_any(&Value::Bool(true)),
        AnyValue::Boolean(true)
    ));
    assert!(matches!(
        json_to_any(&Value::Number(serde_json::Number::from(7))),
        AnyValue::Int(7)
    ));
    assert!(matches!(
        json_to_any(&serde_json::json!(3.5)),
        AnyValue::Double(value) if (value - 3.5).abs() < f64::EPSILON
    ));
    assert!(matches!(
        json_to_any(&Value::String("ok".to_string())),
        AnyValue::String(_)
    ));
    assert!(matches!(
        json_to_any(&serde_json::json!({"nested": true})),
        AnyValue::String(_)
    ));
    assert!(matches!(
        json_to_any(&Value::Number(serde_json::Number::from(u64::MAX))),
        AnyValue::String(_)
    ));
    assert!(parse_hex_u128("0123456789abcdef0123456789abcdef").is_some());
    assert!(parse_hex_u128("short").is_none());
    assert!(parse_hex_u64("0123456789abcdef").is_some());
    assert!(parse_hex_u64("also-short").is_none());
}

#[test]
fn emit_log_is_safe_without_provider_and_with_invalid_trace_ids() {
    let _guard = reset_logs_test_state();
    emit_log(&LogEvent {
        level: "NOISE".to_string(),
        target: "tests.otel.logs".to_string(),
        message: "no provider".to_string(),
        context: BTreeMap::new(),
        trace_id: None,
        span_id: None,
        event_metadata: None,
    });

    let mut cfg = test_config();
    cfg.logging.otlp_endpoint = Some("http://127.0.0.1:4318/v1/logs".to_string());
    cfg.exporter.logs_fail_open = true;
    let resource = super::super::resource::build_resource(&cfg);
    let installed =
        install_logger_provider(&cfg, resource).expect("install should succeed for valid endpoint");
    assert!(installed);
    assert!(logger_provider_installed());

    emit_log(&LogEvent {
        level: "NOISE".to_string(),
        target: "tests.otel.logs".to_string(),
        message: "invalid trace ids".to_string(),
        context: BTreeMap::new(),
        trace_id: Some("not-hex".to_string()),
        span_id: Some("also-not-hex".to_string()),
        event_metadata: None,
    });

    shutdown_logger_provider();
    assert!(!logger_provider_installed());
}

#[test]
fn emit_log_accepts_valid_trace_ids_and_context_attributes() {
    let _guard = reset_logs_test_state();
    let mut cfg = test_config();
    cfg.logging.otlp_endpoint = Some("http://127.0.0.1:4318/v1/logs".to_string());
    cfg.exporter.logs_fail_open = true;
    let resource = super::super::resource::build_resource(&cfg);
    let installed =
        install_logger_provider(&cfg, resource).expect("install should succeed for valid endpoint");
    assert!(installed);

    let mut context = BTreeMap::new();
    context.insert("attempt".to_string(), serde_json::json!(2));
    emit_log(&LogEvent {
        level: "INFO".to_string(),
        target: "tests.otel.logs".to_string(),
        message: "valid trace ids".to_string(),
        context,
        trace_id: Some("0123456789abcdef0123456789abcdef".to_string()),
        span_id: Some("0123456789abcdef".to_string()),
        event_metadata: None,
    });

    shutdown_logger_provider();
    assert!(!logger_provider_installed());
}

#[derive(Debug)]
struct ShutdownErrorLogProcessor;

impl LogProcessor for ShutdownErrorLogProcessor {
    fn emit(&self, _record: &mut SdkLogRecord, _instrumentation: &InstrumentationScope) {}

    fn force_flush(&self) -> OTelSdkResult {
        Ok(())
    }

    fn shutdown_with_timeout(&self, _timeout: Duration) -> OTelSdkResult {
        Err(OTelSdkError::InternalFailure("test shutdown".into()))
    }
}

#[test]
fn shutdown_logger_provider_clears_provider_even_when_processor_shutdown_errors() {
    let _guard = reset_logs_test_state();
    shutdown_logger_provider();
    let provider = SdkLoggerProvider::builder()
        .with_resource(super::super::resource::build_resource(&test_config()))
        .with_log_processor(ShutdownErrorLogProcessor)
        .build();
    *logger_provider_slot()
        .lock()
        .expect("logger provider lock poisoned") = Some(InstalledLoggerProvider {
        provider: Arc::new(provider),
        runtime: ProvideTokioRuntime::test(),
    });

    shutdown_logger_provider();

    assert!(!logger_provider_installed());
}
