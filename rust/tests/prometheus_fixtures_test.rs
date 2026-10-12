// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! The exporter_selection, listener_path, listener_port, translation_strategy
//! and handler_status cases of spec/prometheus_fixtures.yaml, read from the
//! file and run through the public API.

use std::collections::HashMap;

use provide_telemetry::testing::{acquire_test_state_lock, reset_telemetry_state};
use provide_telemetry::{
    adopt_global_providers, metrics_handler, setup_telemetry, shutdown_telemetry, AdoptedProviders,
    TelemetryConfig,
};
use serde_json::Value;

fn fixtures() -> Value {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../spec/prometheus_fixtures.yaml"
    );
    serde_saphyr::from_str(&std::fs::read_to_string(path).expect("fixtures readable"))
        .expect("fixtures parse")
}

fn cases(section: &str) -> Vec<Value> {
    fixtures()[section]
        .as_array()
        .unwrap_or_else(|| panic!("{section} is a list"))
        .clone()
}

fn env_with(key: &str, value: &Value) -> HashMap<String, String> {
    match value.as_str() {
        Some(text) => HashMap::from([(key.to_string(), text.to_string())]),
        None => HashMap::new(),
    }
}

#[test]
fn exporter_selection_cases() {
    let cases = cases("exporter_selection");
    assert_eq!(cases.len(), 26);
    for case in cases {
        let id = case["id"].as_str().unwrap();
        let env: HashMap<String, String> = case["env"]
            .as_object()
            .unwrap()
            .iter()
            .map(|(k, v)| (k.clone(), v.as_str().unwrap().to_string()))
            .collect();
        let parsed = TelemetryConfig::from_map(&env);
        if case["error"].as_bool() == Some(true) {
            assert!(parsed.is_err(), "{id}");
            continue;
        }
        let metrics = parsed.unwrap_or_else(|e| panic!("{id}: {e}")).metrics;
        let mut effective = Vec::new();
        if metrics.otlp_reader_enabled() {
            effective.push("otlp");
        }
        if metrics.prometheus_reader_enabled() {
            effective.push("prometheus");
        }
        let expected: Vec<&str> = case["exporters"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap())
            .collect();
        assert_eq!(effective, expected, "{id}");
        assert_eq!(
            metrics.prometheus_listener_enabled(),
            case["listener"].as_bool().unwrap(),
            "{id}"
        );
        let warnings: Vec<&str> = case["warnings"]
            .as_array()
            .map(|seq| seq.iter().map(|v| v.as_str().unwrap()).collect())
            .unwrap_or_default();
        assert_eq!(metrics.exporter_warnings, warnings, "{id}");
    }
}

#[test]
fn listener_path_cases() {
    for case in cases("listener_path") {
        let id = case["id"].as_str().unwrap();
        let parsed =
            TelemetryConfig::from_map(&env_with("PROVIDE_METRICS_PROMETHEUS_PATH", &case["value"]));
        match case["path"].as_str() {
            Some(path) => assert_eq!(parsed.unwrap().metrics.prometheus.path, path, "{id}"),
            None => assert!(parsed.is_err(), "{id}"),
        }
    }
}

#[test]
fn listener_port_cases() {
    for case in cases("listener_port") {
        let id = case["id"].as_str().unwrap();
        let parsed =
            TelemetryConfig::from_map(&env_with("OTEL_EXPORTER_PROMETHEUS_PORT", &case["value"]));
        match case["port"].as_u64() {
            Some(port) => assert_eq!(
                u64::from(parsed.unwrap().metrics.prometheus.port),
                port,
                "{id}"
            ),
            None => assert!(parsed.is_err(), "{id}"),
        }
    }
}

#[test]
fn translation_strategy_cases() {
    for case in cases("translation_strategy") {
        let id = case["id"].as_str().unwrap();
        let parsed = TelemetryConfig::from_map(&env_with(
            "PROVIDE_METRICS_PROMETHEUS_TRANSLATION",
            &case["value"],
        ));
        match case["strategy"].as_str() {
            Some(strategy) => assert_eq!(
                parsed.unwrap().metrics.prometheus.translation,
                strategy,
                "{id}"
            ),
            None => assert!(parsed.is_err(), "{id}"),
        }
    }
}

#[test]
fn an_explicit_config_is_validated_like_the_environment() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    let mut bad_exporter = TelemetryConfig::default();
    bad_exporter.metrics.exporters = vec!["statsd".to_string()];
    let err = setup_telemetry(Some(bad_exporter)).unwrap_err();
    assert_eq!(err.message, "metrics exporters: unknown \"statsd\"");
    let mut bad_path = TelemetryConfig::default();
    bad_path.metrics.prometheus.path = "metrics".to_string();
    let err = setup_telemetry(Some(bad_path)).unwrap_err();
    assert!(
        err.message.starts_with("PROVIDE_METRICS_PROMETHEUS_PATH"),
        "{}",
        err.message
    );
    reset_telemetry_state();
}

fn prometheus_config() -> TelemetryConfig {
    let mut config = TelemetryConfig::default();
    config.tracing.enabled = false;
    config.metrics.exporters = vec!["prometheus".to_string()];
    config
}

/// Bring the process into one of the handler_status states.
fn enter(state: &str) {
    reset_telemetry_state();
    match state {
        "not_set_up" => {}
        "shut_down" => {
            setup_telemetry(Some(prometheus_config())).unwrap();
            shutdown_telemetry(None).unwrap();
        }
        "metrics_disabled" => {
            let mut config = prometheus_config();
            config.metrics.enabled = false;
            setup_telemetry(Some(config)).unwrap();
        }
        "host_provider" => {
            adopt_global_providers(AdoptedProviders::all());
            setup_telemetry(Some(prometheus_config())).unwrap();
        }
        "ready" => {
            setup_telemetry(Some(prometheus_config())).unwrap();
        }
        other => panic!("unknown state {other}"),
    }
}

#[test]
fn handler_status_cases() {
    let _guard = acquire_test_state_lock();
    let cases = cases("handler_status");
    assert_eq!(cases.len(), 6);
    for case in cases {
        let id = case["id"].as_str().unwrap();
        enter(case["state"].as_str().unwrap());
        let method = case["method"].as_str().unwrap_or("GET");
        let response = metrics_handler(method, None);
        let mut expected = case["status"].as_u64().unwrap();
        if expected == 200 && !cfg!(feature = "otel") {
            // Without the SDK there is no reader to serve, only the reason why.
            expected = 503;
        }
        assert_eq!(u64::from(response.status), expected, "{id}");
        if let (200, Some(prefix)) = (response.status, case["content_type_prefix"].as_str()) {
            assert!(response.headers[0].1.starts_with(prefix), "{id}");
        }
        if response.status == 503 {
            let body = String::from_utf8(response.body).unwrap();
            assert!(
                body.starts_with("provide-telemetry: ") && body.ends_with('\n'),
                "{id}"
            );
            assert_eq!(body.lines().count(), 1, "{id}");
        }
    }
    reset_telemetry_state();
}

#[test]
fn not_selecting_prometheus_gives_its_own_reason() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    setup_telemetry(Some(TelemetryConfig::default())).unwrap();
    let body = String::from_utf8(metrics_handler("GET", None).body).unwrap();
    assert_eq!(
        body,
        "provide-telemetry: the Prometheus reader is not enabled (add prometheus to OTEL_METRICS_EXPORTER)\n"
    );
    reset_telemetry_state();
}

#[cfg(not(feature = "otel"))]
#[test]
fn without_the_sdk_the_reason_says_so() {
    let _guard = acquire_test_state_lock();
    enter("ready");
    let body = String::from_utf8(metrics_handler("GET", None).body).unwrap();
    assert_eq!(
        body,
        "provide-telemetry: the OpenTelemetry SDK is not compiled in (enable the otel feature)\n"
    );
    reset_telemetry_state();
}

#[cfg(not(feature = "prometheus-listener"))]
#[test]
fn asking_for_the_listener_without_the_feature_records_setup_error() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    let mut config = prometheus_config();
    config.metrics.prometheus.listen = "true".to_string();
    setup_telemetry(Some(config)).expect("a missing listener never fails setup");
    assert_eq!(
        provide_telemetry::get_health_snapshot()
            .setup_error
            .as_deref(),
        Some("prometheus listener: rebuild provide-telemetry with the prometheus-listener feature")
    );
    reset_telemetry_state();
    setup_telemetry(Some(prometheus_config())).unwrap();
    assert_eq!(provide_telemetry::get_health_snapshot().setup_error, None);
    reset_telemetry_state();
}
