// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! The pull reader against a real SDK provider: every aggregation and number
//! type is converted, collection is cumulative, and shutdown empties it.

use super::*;

use opentelemetry::metrics::MeterProvider as _;
use opentelemetry_sdk::metrics::{Aggregation, Instrument, SdkMeterProvider, Stream};
use opentelemetry_sdk::Resource;

#[mutants::skip] // test helper
fn provider(reader: &PullReader) -> SdkMeterProvider {
    SdkMeterProvider::builder()
        .with_resource(
            Resource::builder_empty()
                .with_attribute(KeyValue::new("service.name", "reader-test"))
                .build(),
        )
        .with_reader(reader.clone())
        .build()
}

#[mutants::skip] // test helper
fn find<'a>(view: &'a ResourceView, name: &str) -> &'a MetricView {
    view.scopes
        .iter()
        .flat_map(|s| s.metrics.iter())
        .find(|m| m.name == name)
        .unwrap_or_else(|| panic!("no metric {name}"))
}

#[test]
fn every_number_type_and_aggregation_converts() {
    let reader = PullReader::new();
    let provider = provider(&reader);
    let meter = provider.meter_with_scope(
        opentelemetry::InstrumentationScope::builder("scope.a")
            .with_version("2.0")
            .build(),
    );
    let route = [KeyValue::new("route", "/a")];
    let f_counter = meter
        .f64_counter("f.counter")
        .with_unit("s")
        .with_description("float counter")
        .build();
    f_counter.add(1.5, &route);
    f_counter.add(1.0, &route);
    meter.u64_counter("u.counter").build().add(7, &[]);
    meter.i64_up_down_counter("i.updown").build().add(-3, &[]);
    meter.f64_gauge("f.gauge").build().record(0.25, &[]);
    meter.u64_gauge("u.gauge").build().record(9, &[]);
    meter.i64_gauge("i.gauge").build().record(-9, &[]);
    let histogram = meter
        .f64_histogram("f.hist")
        .with_boundaries(vec![1.0, 10.0])
        .build();
    histogram.record(0.5, &route);
    histogram.record(5.0, &route);
    meter
        .u64_histogram("u.hist")
        .with_boundaries(vec![1.0])
        .build()
        .record(3, &[]);

    let view = reader.view();
    assert_eq!(
        view.attributes,
        vec![("service.name".to_string(), "reader-test".to_string())]
    );
    let scope = &view.scopes[0];
    assert_eq!(scope.name, "scope.a");
    assert_eq!(scope.version.as_deref(), Some("2.0"));

    let counter = find(&view, "f.counter");
    assert_eq!(counter.unit, "s");
    assert_eq!(counter.description, "float counter");
    assert_eq!(
        counter.points,
        Points::Sum {
            monotonic: true,
            points: vec![(vec![("route".to_string(), "/a".to_string())], 2.5)],
        }
    );
    assert_eq!(
        find(&view, "u.counter").points,
        Points::Sum {
            monotonic: true,
            points: vec![(Vec::new(), 7.0)],
        }
    );
    assert_eq!(
        find(&view, "i.updown").points,
        Points::Sum {
            monotonic: false,
            points: vec![(Vec::new(), -3.0)],
        }
    );
    assert_eq!(
        find(&view, "f.gauge").points,
        Points::Gauge(vec![(Vec::new(), 0.25)])
    );
    assert_eq!(
        find(&view, "u.gauge").points,
        Points::Gauge(vec![(Vec::new(), 9.0)])
    );
    assert_eq!(
        find(&view, "i.gauge").points,
        Points::Gauge(vec![(Vec::new(), -9.0)])
    );
    assert_eq!(
        find(&view, "f.hist").points,
        Points::Histogram(vec![HistogramPoint {
            attributes: vec![("route".to_string(), "/a".to_string())],
            bounds: vec![1.0, 10.0],
            bucket_counts: vec![1, 1, 0],
            count: 2,
            sum: 5.5,
        }])
    );
    assert_eq!(
        find(&view, "u.hist").points,
        Points::Histogram(vec![HistogramPoint {
            attributes: Vec::new(),
            bounds: vec![1.0],
            bucket_counts: vec![0, 1],
            count: 1,
            sum: 3.0,
        }])
    );

    // Cumulative: a second collection keeps the totals.
    f_counter.add(1.0, &route);
    assert_eq!(
        find(&reader.view(), "f.counter").points,
        Points::Sum {
            monotonic: true,
            points: vec![(vec![("route".to_string(), "/a".to_string())], 3.5)],
        }
    );
    provider
        .force_flush()
        .expect("pull reader flush is a no-op");
    provider.shutdown().expect("shutdown");
}

#[test]
fn exponential_histograms_are_skipped() {
    let reader = PullReader::new();
    let provider = SdkMeterProvider::builder()
        .with_reader(reader.clone())
        .with_view(|instrument: &Instrument| {
            (instrument.name() == "expo").then(|| {
                Stream::builder()
                    .with_aggregation(Aggregation::Base2ExponentialHistogram {
                        max_size: 160,
                        max_scale: 20,
                        record_min_max: true,
                    })
                    .build()
                    .expect("valid stream")
            })
        })
        .build();
    let meter = provider.meter("expo-test");
    meter.f64_histogram("expo").build().record(1.0, &[]);
    meter.f64_gauge("kept").build().record(1.0, &[]);
    let view = reader.view();
    let names: Vec<&str> = view.scopes[0]
        .metrics
        .iter()
        .map(|m| m.name.as_str())
        .collect();
    assert_eq!(names, vec!["kept"]);
    provider.shutdown().expect("shutdown");
}

#[test]
fn a_shut_down_or_unregistered_reader_collects_nothing() {
    let unregistered = PullReader::new();
    assert_eq!(unregistered.view(), ResourceView::default());

    let reader = PullReader::new();
    let provider = provider(&reader);
    provider.meter("m").f64_gauge("g").build().record(1.0, &[]);
    assert!(!reader.view().scopes.is_empty());
    provider.shutdown().expect("shutdown");
    assert_eq!(reader.view(), ResourceView::default());
    let mut metrics = ResourceMetrics::default();
    assert!(reader.collect(&mut metrics).is_err());
}

#[test]
fn the_reader_is_cumulative_for_every_instrument_kind() {
    let reader = PullReader::new();
    for kind in [
        InstrumentKind::Counter,
        InstrumentKind::UpDownCounter,
        InstrumentKind::Histogram,
        InstrumentKind::Gauge,
        InstrumentKind::ObservableCounter,
        InstrumentKind::ObservableUpDownCounter,
        InstrumentKind::ObservableGauge,
    ] {
        assert_eq!(reader.temporality(kind), Temporality::Cumulative);
    }
}
