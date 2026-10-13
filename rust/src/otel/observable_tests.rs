// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Series an observable stops reporting disappear from the next collection.

use super::*;

use std::collections::BTreeMap;
use std::sync::atomic::{AtomicBool, Ordering};

use crate::config::TelemetryConfig;
use crate::observable::{observable_counter, observable_gauge};
use crate::prometheus::render::{HistogramPoint, MetricView, ScopeView};
use crate::testing::{acquire_test_state_lock, reset_telemetry_state};

#[mutants::skip] // test helper
fn attrs(key: &str, value: &str) -> BTreeMap<String, String> {
    BTreeMap::from([(key.to_string(), value.to_string())])
}

#[mutants::skip] // test helper
fn scrape() -> String {
    String::from_utf8(crate::prometheus::render_prometheus(None).unwrap().0).unwrap()
}

#[test]
fn a_series_the_callback_stops_reporting_disappears() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    let mut config = TelemetryConfig::default();
    config.metrics.exporters = vec!["prometheus".to_string()];
    crate::setup_telemetry(Some(config)).expect("setup");

    let both = Arc::new(AtomicBool::new(true));
    let flag = Arc::clone(&both);
    let _gauge = observable_gauge(
        "pool.size",
        move || {
            let mut out = vec![Observation::with_attributes(1.0, attrs("pool", "a"))];
            if flag.load(Ordering::SeqCst) {
                out.push(Observation::with_attributes(2.0, attrs("pool", "b")));
            }
            out
        },
        None,
        None,
    );
    // A second observable under the same name keeps its own series.
    let _twin = observable_counter(
        "pool.size",
        || vec![Observation::with_attributes(5.0, attrs("pool", "c"))],
        None,
        None,
    );
    let text = scrape();
    assert!(text.contains("pool_size{pool=\"a\"} 1\n"), "{text}");
    assert!(text.contains("pool_size{pool=\"b\"} 2\n"), "{text}");

    both.store(false, Ordering::SeqCst);
    let text = scrape();
    assert!(text.contains("pool_size{pool=\"a\"} 1\n"), "{text}");
    assert!(!text.contains("pool=\"b\""), "{text}");

    crate::shutdown_telemetry(None).expect("shutdown");
    assert!(crate::_lock::lock(observed()).is_empty());
    reset_telemetry_state();
}

#[test]
fn only_our_scope_and_value_series_are_filtered() {
    let _guard = acquire_test_state_lock();
    clear_observed();
    record_observed("shared.name", 1, &[Observation::new(1.0)]);
    let histogram = Points::Histogram(vec![HistogramPoint {
        attributes: vec![("k".to_string(), "v".to_string())],
        bounds: Vec::new(),
        bucket_counts: vec![1],
        count: 1,
        sum: 1.0,
    }]);
    let gauge = || Points::Gauge(vec![(vec![("k".to_string(), "v".to_string())], 1.0)]);
    let metric = |points| MetricView {
        name: "shared.name".to_string(),
        unit: String::new(),
        description: String::new(),
        points,
    };
    let mut view = ResourceView {
        attributes: Vec::new(),
        scopes: vec![
            ScopeView {
                name: METER_NAME.to_string(),
                version: None,
                metrics: vec![
                    metric(histogram.clone()),
                    metric(gauge()),
                    MetricView {
                        name: "synchronous.counter".to_string(),
                        ..metric(gauge())
                    },
                ],
            },
            ScopeView {
                name: "host.scope".to_string(),
                version: None,
                metrics: vec![metric(gauge())],
            },
        ],
    };
    retain_observed(&mut view);
    assert_eq!(view.scopes[0].metrics[0].points, histogram);
    assert_eq!(view.scopes[0].metrics[1].points, Points::Gauge(Vec::new()));
    assert_eq!(view.scopes[0].metrics[2].points, gauge());
    assert_eq!(view.scopes[1].metrics[0].points, gauge());
    clear_observed();
}

#[test]
fn attribute_order_does_not_matter() {
    assert_eq!(
        sorted(vec![
            ("b".to_string(), "1".to_string()),
            ("a".to_string(), "2".to_string())
        ]),
        vec![
            ("a".to_string(), "2".to_string()),
            ("b".to_string(), "1".to_string())
        ]
    );
}
