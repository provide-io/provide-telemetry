// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use super::*;

use crate::testing::acquire_test_state_lock;

fn env_map(entries: &[(&str, &str)]) -> HashMap<String, String> {
    entries
        .iter()
        .map(|(key, value)| ((*key).to_string(), (*value).to_string()))
        .collect()
}

#[test]
fn from_env_test_reads_process_environment_wrapper() {
    let _guard = acquire_test_state_lock();
    std::env::set_var("PROVIDE_TELEMETRY_SERVICE_NAME", "env-wrapper");
    std::env::set_var("PROVIDE_TELEMETRY_ENV", "staging");
    std::env::set_var("PROVIDE_TELEMETRY_VERSION", "9.9.9");
    std::env::set_var("PROVIDE_LOG_FORMAT", "json");
    std::env::set_var("PROVIDE_LOG_INCLUDE_TIMESTAMP", "off");

    let cfg = TelemetryConfig::from_env().expect("process env should parse");

    std::env::remove_var("PROVIDE_TELEMETRY_SERVICE_NAME");
    std::env::remove_var("PROVIDE_TELEMETRY_ENV");
    std::env::remove_var("PROVIDE_TELEMETRY_VERSION");
    std::env::remove_var("PROVIDE_LOG_FORMAT");
    std::env::remove_var("PROVIDE_LOG_INCLUDE_TIMESTAMP");

    assert_eq!(cfg.service_name, "env-wrapper");
    assert_eq!(cfg.environment, "staging");
    assert_eq!(cfg.version, "9.9.9");
    assert_eq!(cfg.logging.fmt, "json");
    assert!(!cfg.logging.include_timestamp);
}

#[test]
fn from_map_test_parses_signal_specific_and_policy_fields() {
    let cfg = TelemetryConfig::from_map(&env_map(&[
        ("PROVIDE_TELEMETRY_STRICT_SCHEMA", "true"),
        ("PROVIDE_LOG_PII_MAX_DEPTH", "3"),
        ("PROVIDE_LOG_LEVEL", "DEBUG"),
        ("PROVIDE_LOG_FORMAT", "json"),
        ("PROVIDE_LOG_INCLUDE_TIMESTAMP", "off"),
        ("PROVIDE_LOG_MODULE_LEVELS", "pkg=debug,pkg.child=warning"),
        ("OTEL_EXPORTER_OTLP_LOGS_HEADERS", "x-log=1"),
        (
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
            "https://logs.example/v1/logs",
        ),
        ("OTEL_EXPORTER_OTLP_LOGS_PROTOCOL", "http/json"),
        ("PROVIDE_TRACE_ENABLED", "false"),
        ("PROVIDE_TRACE_SAMPLE_RATE", "0.25"),
        ("OTEL_EXPORTER_OTLP_TRACES_HEADERS", "x-trace=2"),
        (
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
            "https://traces.example/v1/traces",
        ),
        ("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL", "grpc"),
        ("PROVIDE_METRICS_ENABLED", "no"),
        ("OTEL_EXPORTER_OTLP_METRICS_HEADERS", "x-metric=3"),
        (
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
            "https://metrics.example/v1/metrics",
        ),
        ("OTEL_EXPORTER_OTLP_METRICS_PROTOCOL", "http/protobuf"),
        ("OTEL_METRIC_EXPORT_INTERVAL", "5000"),
        ("PROVIDE_TELEMETRY_STRICT_EVENT_NAME", "yes"),
        ("PROVIDE_TELEMETRY_REQUIRED_KEYS", "request_id, actor_id"),
        ("PROVIDE_SAMPLING_LOGS_RATE", "0.1"),
        ("PROVIDE_SAMPLING_TRACES_RATE", "0.2"),
        ("PROVIDE_SAMPLING_METRICS_RATE", "0.3"),
        ("PROVIDE_BACKPRESSURE_LOGS_MAXSIZE", "11"),
        ("PROVIDE_BACKPRESSURE_TRACES_MAXSIZE", "12"),
        ("PROVIDE_BACKPRESSURE_METRICS_MAXSIZE", "13"),
        ("PROVIDE_EXPORTER_LOGS_RETRIES", "2"),
        ("PROVIDE_EXPORTER_TRACES_RETRIES", "3"),
        ("PROVIDE_EXPORTER_METRICS_RETRIES", "4"),
        ("PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS", "1.5"),
        ("PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS", "2.5"),
        ("PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS", "3.5"),
        ("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS", "4.5"),
        ("PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS", "5.5"),
        ("PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS", "6.5"),
        ("PROVIDE_EXPORTER_LOGS_FAIL_OPEN", "false"),
        ("PROVIDE_EXPORTER_TRACES_FAIL_OPEN", "off"),
        ("PROVIDE_EXPORTER_METRICS_FAIL_OPEN", "no"),
        ("PROVIDE_SLO_ENABLE_RED_METRICS", "true"),
        ("PROVIDE_SLO_ENABLE_USE_METRICS", "on"),
        ("PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH", "256"),
        ("PROVIDE_SECURITY_MAX_ATTR_COUNT", "16"),
        ("PROVIDE_SECURITY_MAX_NESTING_DEPTH", "4"),
    ]))
    .expect("all explicit env values should parse");

    assert!(cfg.strict_schema);
    assert_eq!(cfg.pii_max_depth, 3);
    assert_eq!(cfg.logging.level, "DEBUG");
    assert_eq!(cfg.logging.fmt, "json");
    assert!(!cfg.logging.include_timestamp);
    assert_eq!(
        cfg.logging.module_levels.get("pkg").map(String::as_str),
        Some("DEBUG")
    );
    assert_eq!(
        cfg.logging
            .module_levels
            .get("pkg.child")
            .map(String::as_str),
        Some("WARNING")
    );
    assert_eq!(
        cfg.logging.otlp_headers.get("x-log").map(String::as_str),
        Some("1")
    );
    assert_eq!(
        cfg.logging.otlp_endpoint.as_deref(),
        Some("https://logs.example/v1/logs")
    );
    assert_eq!(cfg.logging.otlp_protocol, "http/json");

    assert!(!cfg.tracing.enabled);
    assert!((cfg.tracing.sample_rate - 0.25).abs() < f64::EPSILON);
    assert_eq!(
        cfg.tracing.otlp_headers.get("x-trace").map(String::as_str),
        Some("2")
    );
    assert_eq!(
        cfg.tracing.otlp_endpoint.as_deref(),
        Some("https://traces.example/v1/traces")
    );
    assert_eq!(cfg.tracing.otlp_protocol, "grpc");

    assert!(!cfg.metrics.enabled);
    assert_eq!(
        cfg.metrics.otlp_headers.get("x-metric").map(String::as_str),
        Some("3")
    );
    assert_eq!(
        cfg.metrics.otlp_endpoint.as_deref(),
        Some("https://metrics.example/v1/metrics")
    );
    assert_eq!(cfg.metrics.otlp_protocol, "http/protobuf");
    assert_eq!(cfg.metrics.metric_export_interval_ms, 5_000);

    assert!(cfg.event_schema.strict_event_name);
    assert_eq!(
        cfg.event_schema.required_keys,
        vec!["request_id", "actor_id"]
    );
    assert!((cfg.sampling.logs_rate - 0.1).abs() < f64::EPSILON);
    assert!((cfg.sampling.traces_rate - 0.2).abs() < f64::EPSILON);
    assert!((cfg.sampling.metrics_rate - 0.3).abs() < f64::EPSILON);
    assert_eq!(cfg.backpressure.logs_maxsize, 11);
    assert_eq!(cfg.backpressure.traces_maxsize, 12);
    assert_eq!(cfg.backpressure.metrics_maxsize, 13);
    assert_eq!(cfg.exporter.logs_retries, 2);
    assert_eq!(cfg.exporter.traces_retries, 3);
    assert_eq!(cfg.exporter.metrics_retries, 4);
    assert!((cfg.exporter.logs_backoff_seconds - 1.5).abs() < f64::EPSILON);
    assert!((cfg.exporter.traces_backoff_seconds - 2.5).abs() < f64::EPSILON);
    assert!((cfg.exporter.metrics_backoff_seconds - 3.5).abs() < f64::EPSILON);
    assert!((cfg.exporter.logs_timeout_seconds - 4.5).abs() < f64::EPSILON);
    assert!((cfg.exporter.traces_timeout_seconds - 5.5).abs() < f64::EPSILON);
    assert!((cfg.exporter.metrics_timeout_seconds - 6.5).abs() < f64::EPSILON);
    assert!(!cfg.exporter.logs_fail_open);
    assert!(!cfg.exporter.traces_fail_open);
    assert!(!cfg.exporter.metrics_fail_open);
    assert!(cfg.slo.enable_red_metrics);
    assert!(cfg.slo.enable_use_metrics);
    assert_eq!(cfg.security.max_attr_value_length, 256);
    assert_eq!(cfg.security.max_attr_count, 16);
    assert_eq!(cfg.security.max_nesting_depth, 4);
}

#[test]
fn from_map_test_shared_otlp_defaults_fill_all_three_signals() {
    let cfg = TelemetryConfig::from_map(&env_map(&[
        ("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=Bearer%20token"),
        ("OTEL_EXPORTER_OTLP_ENDPOINT", "https://collector:4318/"),
        ("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf"),
    ]))
    .expect("shared OTLP env vars should parse");

    assert_eq!(
        cfg.logging
            .otlp_headers
            .get("Authorization")
            .map(String::as_str),
        Some("Bearer token")
    );
    assert_eq!(cfg.tracing.otlp_headers, cfg.logging.otlp_headers);
    assert_eq!(cfg.metrics.otlp_headers, cfg.logging.otlp_headers);
    assert_eq!(
        cfg.logging.otlp_endpoint.as_deref(),
        Some("https://collector:4318/v1/logs")
    );
    assert_eq!(
        cfg.tracing.otlp_endpoint.as_deref(),
        Some("https://collector:4318/v1/traces")
    );
    assert_eq!(
        cfg.metrics.otlp_endpoint.as_deref(),
        Some("https://collector:4318/v1/metrics")
    );
    assert_eq!(cfg.logging.otlp_protocol, "http/protobuf");
    assert_eq!(cfg.tracing.otlp_protocol, "http/protobuf");
    assert_eq!(cfg.metrics.otlp_protocol, "http/protobuf");
}

#[test]
fn from_map_test_invalid_scalar_env_values_fail_on_their_own_fields() {
    let cases = [
        ("PROVIDE_TELEMETRY_STRICT_SCHEMA", "maybe"),
        ("PROVIDE_LOG_PII_MAX_DEPTH", "-1"),
        ("PROVIDE_LOG_INCLUDE_TIMESTAMP", "maybe"),
        ("PROVIDE_TRACE_ENABLED", "maybe"),
        ("PROVIDE_TRACE_SAMPLE_RATE", "2.0"),
        ("PROVIDE_METRICS_ENABLED", "maybe"),
        ("OTEL_METRIC_EXPORT_INTERVAL", "-1"),
        ("PROVIDE_TELEMETRY_STRICT_EVENT_NAME", "maybe"),
        ("PROVIDE_SAMPLING_LOGS_RATE", "2.0"),
        ("PROVIDE_SAMPLING_TRACES_RATE", "2.0"),
        ("PROVIDE_SAMPLING_METRICS_RATE", "2.0"),
        ("PROVIDE_BACKPRESSURE_LOGS_MAXSIZE", "-1"),
        ("PROVIDE_BACKPRESSURE_TRACES_MAXSIZE", "-1"),
        ("PROVIDE_BACKPRESSURE_METRICS_MAXSIZE", "-1"),
        ("PROVIDE_EXPORTER_LOGS_RETRIES", "-1"),
        ("PROVIDE_EXPORTER_TRACES_RETRIES", "-1"),
        ("PROVIDE_EXPORTER_METRICS_RETRIES", "-1"),
        ("PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS", "-1"),
        ("PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS", "-1"),
        ("PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS", "-1"),
        ("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS", "-1"),
        ("PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS", "-1"),
        ("PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS", "-1"),
        ("PROVIDE_EXPORTER_LOGS_FAIL_OPEN", "maybe"),
        ("PROVIDE_EXPORTER_TRACES_FAIL_OPEN", "maybe"),
        ("PROVIDE_EXPORTER_METRICS_FAIL_OPEN", "maybe"),
        ("PROVIDE_SLO_ENABLE_RED_METRICS", "maybe"),
        ("PROVIDE_SLO_ENABLE_USE_METRICS", "maybe"),
        ("PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH", "-1"),
        ("PROVIDE_SECURITY_MAX_ATTR_COUNT", "-1"),
        ("PROVIDE_SECURITY_MAX_NESTING_DEPTH", "-1"),
    ];

    for (key, value) in cases {
        let cfg = env_map(&[(key, value)]);
        let err = TelemetryConfig::from_map(&cfg)
            .expect_err(&format!("expected {key}={value:?} to fail"));
        assert!(
            err.message.contains(key),
            "error for {key} should mention the field, got: {}",
            err.message
        );
    }
}

#[test]
fn from_map_test_invalid_otlp_header_env_values_are_skipped_without_failing_parse() {
    for key in [
        "OTEL_EXPORTER_OTLP_HEADERS",
        "OTEL_EXPORTER_OTLP_LOGS_HEADERS",
        "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
        "OTEL_EXPORTER_OTLP_METRICS_HEADERS",
    ] {
        let cfg = TelemetryConfig::from_map(&env_map(&[(key, "bad=%ZZ,ok=value")]))
            .expect("invalid header pairs should be ignored");
        let headers = match key {
            "OTEL_EXPORTER_OTLP_LOGS_HEADERS" => cfg.logging.otlp_headers,
            "OTEL_EXPORTER_OTLP_TRACES_HEADERS" => cfg.tracing.otlp_headers,
            "OTEL_EXPORTER_OTLP_METRICS_HEADERS" => cfg.metrics.otlp_headers,
            _ => cfg.logging.otlp_headers,
        };
        assert_eq!(headers.get("ok").map(String::as_str), Some("value"));
        assert!(!headers.contains_key("bad"));
    }
}
