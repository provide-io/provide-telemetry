// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use std::collections::HashMap;

use provide_telemetry::{
    ConfigurationError, EventSchemaError, RuntimeOverrides, TelemetryConfig, TelemetryError,
};

fn env_map(entries: &[(&str, &str)]) -> HashMap<String, String> {
    entries
        .iter()
        .map(|(key, value)| ((*key).to_string(), (*value).to_string()))
        .collect()
}

#[test]
fn config_test_defaults_match_repo_contract() {
    let cfg = TelemetryConfig::from_map(&HashMap::new()).expect("empty env should parse");

    assert_eq!(cfg.service_name, "provide-service");
    assert_eq!(cfg.environment, "dev");
    assert_eq!(cfg.version, "0.0.0");
    assert!(!cfg.strict_schema);
    assert_eq!(cfg.pii_max_depth, 8);
    assert_eq!(cfg.logging.level, "INFO");
    assert_eq!(cfg.logging.fmt, "console");
    assert!(cfg.logging.otlp_headers.is_empty());
    assert!(cfg.tracing.enabled);
    assert!(cfg.metrics.enabled);
}

#[test]
fn config_test_env_overrides_and_header_parsing_follow_repo_behavior() {
    let cfg = TelemetryConfig::from_map(&env_map(&[
        ("PROVIDE_TELEMETRY_SERVICE_NAME", "svc-rust"),
        ("PROVIDE_TELEMETRY_ENV", "staging"),
        ("PROVIDE_TELEMETRY_VERSION", "1.2.3"),
        ("PROVIDE_TELEMETRY_STRICT_SCHEMA", "true"),
        ("PROVIDE_LOG_PII_MAX_DEPTH", "3"),
        (
            "OTEL_EXPORTER_OTLP_HEADERS",
            "Authorization=Bearer%20token%3D123,X-Custom%20Key=value%20with%20spaces,a+b=c+d,badpair,bad=%ZZ,=skip",
        ),
    ]))
    .expect("valid env should parse");

    assert_eq!(cfg.service_name, "svc-rust");
    assert_eq!(cfg.environment, "staging");
    assert_eq!(cfg.version, "1.2.3");
    assert!(cfg.strict_schema);
    assert_eq!(cfg.pii_max_depth, 3);
    assert_eq!(
        cfg.logging
            .otlp_headers
            .get("Authorization")
            .map(String::as_str),
        Some("Bearer token=123")
    );
    assert_eq!(
        cfg.logging
            .otlp_headers
            .get("X-Custom Key")
            .map(String::as_str),
        Some("value with spaces")
    );
    assert_eq!(
        cfg.logging.otlp_headers.get("a+b").map(String::as_str),
        Some("c+d")
    );
    assert!(!cfg.logging.otlp_headers.contains_key(""));
    assert!(!cfg.logging.otlp_headers.contains_key("badpair"));
    assert!(!cfg.logging.otlp_headers.contains_key("bad"));
    assert_eq!(cfg.tracing.otlp_headers, cfg.logging.otlp_headers);
    assert_eq!(cfg.metrics.otlp_headers, cfg.logging.otlp_headers);
}

#[test]
fn config_test_fallback_env_names_are_supported() {
    let cfg = TelemetryConfig::from_map(&env_map(&[
        ("PROVIDE_ENV", "production"),
        ("PROVIDE_VERSION", "9.9.9"),
    ]))
    .expect("fallback env names should parse");

    assert_eq!(cfg.environment, "production");
    assert_eq!(cfg.version, "9.9.9");
}

#[test]
fn config_test_invalid_boolean_returns_configuration_error() {
    let err = TelemetryConfig::from_map(&env_map(&[("PROVIDE_TRACE_ENABLED", "definitely")]))
        .expect_err("invalid boolean should fail");

    assert!(err.message.contains("PROVIDE_TRACE_ENABLED"));
}

#[test]
fn config_test_exported_types_are_distinct_and_constructible() {
    let telemetry = TelemetryError::new("telemetry blew up");
    let config = ConfigurationError::new("config invalid");
    let schema = EventSchemaError::new("schema invalid");
    let overrides = RuntimeOverrides::default();

    assert_eq!(telemetry.message, "telemetry blew up");
    assert_eq!(config.message, "config invalid");
    assert_eq!(schema.message, "schema invalid");
    assert_eq!(config.to_string(), "config invalid");
    assert_eq!(schema.to_string(), "schema invalid");
    assert!(overrides.strict_schema.is_none());
}
