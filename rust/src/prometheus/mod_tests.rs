// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! The endpoint status, the Tier 2 handler and the health families, including
//! every health_metrics case in spec/prometheus_fixtures.yaml.

use super::*;

use crate::testing::acquire_test_state_lock;
use render::{Labels, MetricView, Points, ScopeView};
use serde_yaml::Value;

#[mutants::skip] // test helper
fn fixtures() -> Value {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../spec/prometheus_fixtures.yaml"
    );
    serde_yaml::from_str(&std::fs::read_to_string(path).expect("fixtures readable"))
        .expect("fixtures parse")
}

#[mutants::skip] // test helper
fn snapshot_from(fields: &Value) -> HealthSnapshot {
    let u = |key: &str| fields[key].as_u64().unwrap();
    let f = |key: &str| fields[key].as_f64().unwrap();
    let s = |key: &str| fields[key].as_str().unwrap().to_string();
    HealthSnapshot {
        emitted_logs: u("emitted_logs"),
        emitted_traces: u("emitted_traces"),
        emitted_metrics: u("emitted_metrics"),
        dropped_logs: u("dropped_logs"),
        dropped_traces: u("dropped_traces"),
        dropped_metrics: u("dropped_metrics"),
        export_failures_logs: u("export_failures_logs"),
        export_failures_traces: u("export_failures_traces"),
        export_failures_metrics: u("export_failures_metrics"),
        retries_logs: u("retries_logs"),
        retries_traces: u("retries_traces"),
        retries_metrics: u("retries_metrics"),
        export_latency_ms_logs: f("export_latency_ms_logs"),
        export_latency_ms_traces: f("export_latency_ms_traces"),
        export_latency_ms_metrics: f("export_latency_ms_metrics"),
        async_blocking_risk_logs: u("async_blocking_risk_logs"),
        async_blocking_risk_traces: u("async_blocking_risk_traces"),
        async_blocking_risk_metrics: u("async_blocking_risk_metrics"),
        circuit_state_logs: s("circuit_state_logs"),
        circuit_state_traces: s("circuit_state_traces"),
        circuit_state_metrics: s("circuit_state_metrics"),
        circuit_open_count_logs: u("circuit_open_count_logs"),
        circuit_open_count_traces: u("circuit_open_count_traces"),
        circuit_open_count_metrics: u("circuit_open_count_metrics"),
        setup_error: Some(s("setup_error")),
        receipt_failures: u("receipt_failures"),
    }
}

/// Every sample as (metric, labels, value).
#[mutants::skip] // test helper
fn samples(families: &[Family]) -> Vec<(String, Labels, f64)> {
    families
        .iter()
        .flat_map(|f| {
            f.samples
                .iter()
                .map(|s| (format!("{}{}", f.name, s.suffix), s.labels.clone(), s.value))
        })
        .collect()
}

#[mutants::skip] // test helper
fn expected_samples(case: &Value) -> Vec<(String, Labels, f64)> {
    case["expected_samples"]
        .as_sequence()
        .unwrap()
        .iter()
        .map(|sample| {
            let labels = sample["labels"]
                .as_mapping()
                .unwrap()
                .iter()
                .map(|(k, v)| {
                    (
                        k.as_str().unwrap().to_string(),
                        v.as_str().unwrap().to_string(),
                    )
                })
                .collect();
            (
                sample["metric"].as_str().unwrap().to_string(),
                labels,
                sample["value"].as_f64().unwrap(),
            )
        })
        .collect()
}

#[test]
fn health_metrics_fixture_cases() {
    let doc = fixtures();
    let cases = doc["health_metrics"].as_sequence().unwrap();
    let full = cases
        .iter()
        .find(|c| c["id"] == "full_snapshot")
        .expect("full_snapshot case");
    let base = snapshot_from(&full["snapshot"]);
    // Compared by sample, not by order.
    let got = samples(&health_families(&base));
    let expected = expected_samples(full);
    assert_eq!(got.len(), expected.len());
    for sample in &expected {
        assert!(got.contains(sample), "missing {sample:?}");
    }

    let empty_error = cases
        .iter()
        .find(|c| c["id"] == "setup_error_empty_reads_zero")
        .expect("setup_error_empty_reads_zero case");
    let snapshot = HealthSnapshot {
        setup_error: Some(String::new()),
        ..base.clone()
    };
    for expected in expected_samples(empty_error) {
        assert!(
            samples(&health_families(&snapshot)).contains(&expected),
            "{expected:?}"
        );
    }
    // No error at all reads zero too.
    let none = HealthSnapshot {
        setup_error: None,
        ..base
    };
    let got = samples(&health_families(&none));
    assert!(got.contains(&("provide_telemetry_setup_error".to_string(), Vec::new(), 0.0)));
}

#[test]
fn health_types_and_unknown_circuit_state() {
    let families = health_families(&HealthSnapshot::default());
    let kinds: Vec<(&str, PromType)> = families.iter().map(|f| (f.name.as_str(), f.kind)).collect();
    assert_eq!(
        kinds,
        vec![
            ("provide_telemetry_emitted_total", PromType::Counter),
            ("provide_telemetry_dropped_total", PromType::Counter),
            ("provide_telemetry_export_failures_total", PromType::Counter),
            ("provide_telemetry_export_retries_total", PromType::Counter),
            (
                "provide_telemetry_export_latency_milliseconds",
                PromType::Gauge
            ),
            (
                "provide_telemetry_async_blocking_risk_total",
                PromType::Counter
            ),
            ("provide_telemetry_circuit_state", PromType::Gauge),
            ("provide_telemetry_circuit_open_total", PromType::Counter),
            ("provide_telemetry_setup_error", PromType::Gauge),
            (
                "provide_telemetry_receipt_failures_total",
                PromType::Counter
            ),
        ]
    );
    // circuit_state_unknown_value: an empty or unrecognised state reads -1.
    assert!(families[6].samples.iter().all(|s| s.value == -1.0));
    assert_eq!(circuit_value("closed"), 0.0);
    assert_eq!(circuit_value("half-open"), 1.0);
    assert_eq!(circuit_value("open"), 2.0);
    assert_eq!(circuit_value("broken"), -1.0);
}

#[test]
fn every_status_has_its_own_reason() {
    let statuses = [
        Status::NotSetUp,
        Status::ShutDown,
        Status::MetricsDisabled,
        Status::HostProvider,
        Status::NotSelected,
        Status::OtelMissing,
        Status::SetupFailed,
    ];
    let reasons: std::collections::HashSet<&str> = statuses.iter().map(|s| s.reason()).collect();
    assert_eq!(reasons.len(), statuses.len());
    for reason in reasons {
        assert!(reason.starts_with("provide-telemetry: "), "{reason}");
        assert!(!reason.contains('\n'));
    }
    assert_eq!(
        Status::MetricsDisabled.reason(),
        "provide-telemetry: metrics are disabled (PROVIDE_METRICS_ENABLED=false)"
    );
}

#[mutants::skip] // test helper
fn fake_collection() -> ResourceView {
    ResourceView {
        attributes: vec![("service.name".to_string(), "svc".to_string())],
        scopes: vec![ScopeView {
            name: "s".to_string(),
            version: None,
            metrics: vec![MetricView {
                name: "jobs.done".to_string(),
                unit: "".to_string(),
                description: "Jobs".to_string(),
                points: Points::Sum {
                    monotonic: true,
                    points: vec![(Vec::new(), 5.0)],
                },
            }],
        }],
    }
}

#[test]
fn handler_serves_get_and_head_and_refuses_other_methods() {
    let _guard = acquire_test_state_lock();
    crate::health::_reset_health_for_tests();
    mark_ready(
        Arc::new(fake_collection),
        RenderOptions {
            strategy: "NoUTF8EscapingWithSuffixes".to_string(),
            scope_labels: false,
            target_info: true,
        },
    );

    let get = metrics_handler("GET", None);
    assert_eq!(get.status, 200);
    assert_eq!(
        get.headers,
        vec![("content-type", render::CONTENT_TYPE_TEXT.to_string())]
    );
    let body = String::from_utf8(get.body).unwrap();
    assert!(body.contains("# HELP jobs_done_total Jobs\n"), "{body}");
    assert!(body.contains("\njobs_done_total 5\n"), "{body}");
    assert!(
        body.contains("target_info{service_name=\"svc\"} 1\n"),
        "{body}"
    );
    assert!(body.contains("provide_telemetry_emitted_total{signal=\"logs\"} 0\n"));

    let utf8 = metrics_handler("GET", Some("text/plain;escaping=allow-utf-8"));
    assert_eq!(
        utf8.headers,
        vec![("content-type", render::CONTENT_TYPE_UTF8.to_string())]
    );
    assert!(String::from_utf8(utf8.body)
        .unwrap()
        .contains("{\"jobs.done_total\"} 5\n"));

    let head = metrics_handler("HEAD", None);
    assert_eq!(head.status, 200);
    assert_eq!(
        head.headers,
        vec![("content-type", render::CONTENT_TYPE_TEXT.to_string())]
    );
    assert!(head.body.is_empty());

    let post = metrics_handler("POST", None);
    assert_eq!(
        post,
        MetricsResponse {
            status: 405,
            headers: vec![
                ("allow", "GET, HEAD".to_string()),
                ("content-type", "text/plain; charset=utf-8".to_string()),
            ],
            body: b"method not allowed\n".to_vec(),
        }
    );
    // Methods are case-sensitive, as in HTTP.
    assert_eq!(metrics_handler("get", None).status, 405);

    let (bytes, content_type) = render_prometheus(None).unwrap();
    assert_eq!(content_type, render::CONTENT_TYPE_TEXT);
    assert!(String::from_utf8(bytes)
        .unwrap()
        .starts_with("# HELP jobs_done_total"));
    set_status(Status::NotSetUp);
}

#[test]
fn handler_answers_503_with_the_reason_until_ready() {
    let _guard = acquire_test_state_lock();
    for status in [Status::NotSetUp, Status::ShutDown, Status::HostProvider] {
        set_status(status);
        let response = metrics_handler("GET", None);
        assert_eq!(
            response,
            MetricsResponse {
                status: 503,
                headers: vec![("content-type", "text/plain; charset=utf-8".to_string())],
                body: format!("{}\n", status.reason()).into_bytes(),
            }
        );
        assert_eq!(metrics_handler("HEAD", None).status, 503);
        let err = render_prometheus(Some("text/plain")).unwrap_err();
        assert_eq!(err.message, status.reason());
    }
    set_status(Status::NotSetUp);
}

#[test]
fn options_follow_the_config() {
    let mut config = crate::config::TelemetryConfig::default();
    config.metrics.prometheus.translation = "NoTranslation".to_string();
    config.metrics.prometheus.scope_labels = true;
    config.metrics.prometheus.target_info = false;
    assert_eq!(
        options_for(&config),
        RenderOptions {
            strategy: "NoTranslation".to_string(),
            scope_labels: true,
            target_info: false,
        }
    );
}

#[test]
fn without_the_sdk_the_status_says_why() {
    let mut config = crate::config::TelemetryConfig::default();
    assert_eq!(status_without_sdk(&config), Status::NotSelected);
    config.metrics.exporters = vec!["prometheus".to_string()];
    assert_eq!(status_without_sdk(&config), Status::OtelMissing);
    config.metrics.enabled = false;
    assert_eq!(status_without_sdk(&config), Status::MetricsDisabled);
}

#[test]
fn health_metric_names_are_recognised() {
    for family in health_families(&HealthSnapshot::default()) {
        assert!(is_health_metric(&family.name), "{}", family.name);
    }
    assert!(!is_health_metric("provide_telemetry_other_total"));
    assert!(!is_health_metric("jobs_done_total"));
}
