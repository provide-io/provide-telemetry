// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! prometheus_metrics.health_metrics.health_otlp: the 26 series reach the
//! provider's readers, uncounted and ungated, and a scrape shows each family once.

use super::*;

use crate::otel::prometheus_reader::PullReader;
use crate::prometheus::render::{MetricView, Points};
use crate::sampling::Signal;
use crate::testing::{acquire_test_state_lock, reset_telemetry_state};

#[mutants::skip] // test helper
fn signal(value: &str) -> Vec<(String, String)> {
    vec![("signal".to_string(), value.to_string())]
}

#[mutants::skip] // test helper
fn metric<'a>(metrics: &'a [MetricView], name: &str) -> &'a MetricView {
    metrics
        .iter()
        .find(|m| m.name == name)
        .unwrap_or_else(|| panic!("no {name}"))
}

#[test]
fn every_health_series_reaches_the_reader_with_its_value_and_type() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    crate::health::increment_dropped(Signal::Traces, 4);
    crate::health::record_export_latency(Signal::Logs, 12.5);
    crate::health::increment_receipt_failures();
    crate::health::set_setup_error(Some("boom".to_string()));
    // Health observations are neither consent-gated nor counted as emitted.
    crate::consent::set_consent_level(crate::consent::ConsentLevel::None);

    let reader = PullReader::new();
    let provider = SdkMeterProvider::builder()
        .with_reader(reader.clone())
        .build();
    register(&provider);
    let view = reader.view();
    let metrics = &view.scopes[0].metrics;
    assert_eq!(view.scopes[0].name, METER_NAME);
    assert_eq!(metrics.len(), 10);
    let series: usize = metrics
        .iter()
        .map(|m| match &m.points {
            Points::Sum { points, .. } | Points::Gauge(points) => points.len(),
            Points::Histogram(_) => panic!("no health family is a histogram"),
        })
        .sum();
    assert_eq!(series, 26);
    for m in metrics {
        assert_eq!(
            (m.unit.as_str(), m.description.as_str()),
            ("", ""),
            "{}",
            m.name
        );
    }

    let dropped = metric(metrics, "provide_telemetry_dropped_total");
    match &dropped.points {
        Points::Sum { monotonic, points } => {
            assert!(monotonic);
            assert!(points.contains(&(signal("traces"), 4.0)));
            assert!(points.contains(&(signal("logs"), 0.0)));
        }
        other => panic!("counter expected, got {other:?}"),
    }
    let latency = metric(metrics, "provide_telemetry_export_latency_milliseconds");
    match &latency.points {
        Points::Gauge(points) => assert!(points.contains(&(signal("logs"), 12.5))),
        other => panic!("gauge expected, got {other:?}"),
    }
    match &metric(metrics, "provide_telemetry_circuit_state").points {
        Points::Gauge(points) => assert!(points.contains(&(signal("metrics"), 0.0))),
        other => panic!("gauge expected, got {other:?}"),
    }
    assert_eq!(
        metric(metrics, "provide_telemetry_setup_error").points,
        Points::Gauge(vec![(Vec::new(), 1.0)])
    );
    assert_eq!(
        metric(metrics, "provide_telemetry_receipt_failures_total").points,
        Points::Sum {
            monotonic: true,
            points: vec![(Vec::new(), 1.0)],
        }
    );
    // Values are re-read at each collection.
    crate::health::set_setup_error(None);
    assert_eq!(
        metric(
            &reader.view().scopes[0].metrics,
            "provide_telemetry_setup_error"
        )
        .points,
        Points::Gauge(vec![(Vec::new(), 0.0)])
    );
    assert_eq!(crate::health::get_health_snapshot().emitted_metrics, 0);
    provider.shutdown().expect("shutdown");
    reset_telemetry_state();
}

#[mutants::skip] // test helper
fn scrape_with(health_otlp: bool) -> String {
    reset_telemetry_state();
    let mut config = crate::config::TelemetryConfig::default();
    config.metrics.exporters = vec!["prometheus".to_string()];
    config.metrics.health_otlp = health_otlp;
    crate::setup_telemetry(Some(config)).expect("setup");
    let before = crate::health::get_health_snapshot().emitted_metrics;
    let first = crate::prometheus::render_prometheus(None).unwrap().0;
    let text = String::from_utf8(crate::prometheus::render_prometheus(None).unwrap().0).unwrap();
    assert!(!first.is_empty());
    assert_eq!(crate::health::get_health_snapshot().emitted_metrics, before);
    reset_telemetry_state();
    text
}

#[test]
fn a_scrape_carries_each_health_family_once_whatever_the_flag() {
    let _guard = acquire_test_state_lock();
    for health_otlp in [false, true] {
        let text = scrape_with(health_otlp);
        for family in health_families(&HealthSnapshot::default()) {
            let header = format!("# TYPE {} ", family.name);
            assert_eq!(
                text.matches(&header).count(),
                1,
                "{header} (health_otlp={health_otlp})"
            );
        }
        assert_eq!(
            text.matches("provide_telemetry_emitted_total{").count(),
            3,
            "health_otlp={health_otlp}"
        );
    }
}
