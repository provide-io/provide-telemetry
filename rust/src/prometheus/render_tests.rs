// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use super::*;

#[mutants::skip] // test helper
fn labels(pairs: &[(&str, &str)]) -> Labels {
    pairs
        .iter()
        .map(|(k, v)| ((*k).to_string(), (*v).to_string()))
        .collect()
}

#[mutants::skip] // test helper
fn options(strategy: &str) -> RenderOptions {
    RenderOptions {
        strategy: strategy.to_string(),
        scope_labels: false,
        target_info: true,
    }
}

#[mutants::skip] // test helper
fn metric(name: &str, unit: &str, points: Points) -> MetricView {
    MetricView {
        name: name.to_string(),
        unit: unit.to_string(),
        description: String::new(),
        points,
    }
}

#[mutants::skip] // test helper
fn one_scope(metrics: Vec<MetricView>) -> ResourceView {
    ResourceView {
        attributes: Labels::new(),
        scopes: vec![ScopeView {
            name: "scope".to_string(),
            version: Some("1.2".to_string()),
            metrics,
        }],
    }
}

#[test]
fn wants_utf8_needs_text_plain_with_the_escaping_parameter() {
    assert!(!wants_utf8(None));
    assert!(!wants_utf8(Some("")));
    assert!(wants_utf8(Some(
        "text/plain;version=1.0.0;escaping=allow-utf-8"
    )));
    assert!(wants_utf8(Some(
        "application/openmetrics-text;version=1.0.0, TEXT/PLAIN ; Escaping=Allow-UTF-8"
    )));
    assert!(!wants_utf8(Some("text/plain;version=0.0.4")));
    assert!(!wants_utf8(Some(
        "application/openmetrics-text;escaping=allow-utf-8"
    )));
    // The parameter must follow the media type, never be it.
    assert!(!wants_utf8(Some("escaping=allow-utf-8")));
}

#[test]
fn effective_strategy_falls_back_to_escaping_without_negotiation() {
    for (configured, utf8, escapes, suffixes) in [
        ("UnderscoreEscapingWithSuffixes", false, true, true),
        ("UnderscoreEscapingWithSuffixes", true, true, true),
        ("NoUTF8EscapingWithSuffixes", false, true, true),
        ("NoUTF8EscapingWithSuffixes", true, false, true),
        ("NoTranslation", false, true, false),
        ("NoTranslation", true, false, false),
    ] {
        assert_eq!(
            effective_strategy(configured, utf8),
            Strategy { escapes, suffixes },
            "{configured} utf8={utf8}"
        );
    }
}

#[test]
fn untranslatable_and_reserved_labels_are_dropped_and_collisions_keep_the_last_value() {
    let escaped = Strategy::named("UnderscoreEscapingWithSuffixes");
    let got = translate_labels(
        &labels(&[
            ("a.b", "1"),
            ("_", "dropped"),
            ("__reserved__", "dropped"),
            ("route", "/a"),
            ("a_b", "2"),
        ]),
        escaped,
    );
    assert_eq!(got, labels(&[("a_b", "2"), ("route", "/a")]));

    let utf8 = Strategy::named("NoTranslation");
    let got = translate_labels(&labels(&[("a.b", "1"), ("__x", "dropped")]), utf8);
    assert_eq!(got, labels(&[("a.b", "1")]));
}

#[test]
fn sums_gauges_and_histograms_become_families() {
    let view = one_scope(vec![
        metric(
            "http.requests",
            "",
            Points::Sum {
                monotonic: true,
                points: vec![(labels(&[("route", "/a")]), 3.0)],
            },
        ),
        metric(
            "queue.depth",
            "",
            Points::Sum {
                monotonic: false,
                points: vec![(Labels::new(), -2.0)],
            },
        ),
        metric(
            "cpu.utilization",
            "1",
            Points::Gauge(vec![(Labels::new(), 0.5)]),
        ),
        metric(
            "latency",
            "ms",
            Points::Histogram(vec![HistogramPoint {
                attributes: labels(&[("route", "/a")]),
                bounds: vec![5.0, 10.0],
                bucket_counts: vec![1, 2, 3],
                count: 6,
                sum: 70.5,
            }]),
        ),
    ]);
    let families = families_from(&view, &options("UnderscoreEscapingWithSuffixes"), false);
    let names: Vec<(&str, PromType)> = families.iter().map(|f| (f.name.as_str(), f.kind)).collect();
    assert_eq!(
        names,
        vec![
            ("cpu_utilization_ratio", PromType::Gauge),
            ("http_requests_total", PromType::Counter),
            ("latency_milliseconds", PromType::Histogram),
            ("queue_depth", PromType::Gauge),
        ]
    );
    let histogram = &families[2];
    let samples: Vec<(&str, Labels, f64)> = histogram
        .samples
        .iter()
        .map(|s| (s.suffix, s.labels.clone(), s.value))
        .collect();
    assert_eq!(
        samples,
        vec![
            ("_bucket", labels(&[("route", "/a"), ("le", "5")]), 1.0),
            ("_bucket", labels(&[("route", "/a"), ("le", "10")]), 3.0),
            ("_bucket", labels(&[("route", "/a"), ("le", "+Inf")]), 6.0),
            ("_sum", labels(&[("route", "/a")]), 70.5),
            ("_count", labels(&[("route", "/a")]), 6.0),
        ]
    );
    assert_eq!(families[1].samples[0].labels, labels(&[("route", "/a")]));
    assert_eq!(families[3].samples[0].value, -2.0);
}

#[test]
fn scope_labels_target_info_and_untranslatable_names() {
    let mut view = one_scope(vec![
        metric("x", "", Points::Gauge(vec![(labels(&[("k", "v")]), 1.0)])),
        // translates to nothing and is skipped
        metric("_._", "", Points::Gauge(vec![(Labels::new(), 1.0)])),
    ]);
    view.attributes = labels(&[("service.name", "svc"), ("_", "dropped")]);
    view.scopes.push(ScopeView {
        name: "unversioned".to_string(),
        version: Some(String::new()),
        metrics: vec![metric("y", "", Points::Gauge(vec![(Labels::new(), 2.0)]))],
    });
    view.scopes.push(ScopeView {
        name: "none".to_string(),
        version: None,
        metrics: vec![metric("z", "", Points::Gauge(vec![(Labels::new(), 3.0)]))],
    });
    let opts = RenderOptions {
        strategy: "UnderscoreEscapingWithSuffixes".to_string(),
        scope_labels: true,
        target_info: true,
    };
    let families = families_from(&view, &opts, false);
    let by_name = |name: &str| families.iter().find(|f| f.name == name).unwrap();
    assert_eq!(
        by_name("x").samples[0].labels,
        labels(&[
            ("k", "v"),
            ("otel_scope_name", "scope"),
            ("otel_scope_version", "1.2")
        ])
    );
    assert_eq!(
        by_name("y").samples[0].labels,
        labels(&[("otel_scope_name", "unversioned")])
    );
    assert_eq!(
        by_name("z").samples[0].labels,
        labels(&[("otel_scope_name", "none")])
    );
    let info = by_name("target_info");
    assert_eq!(info.help, "Target metadata");
    assert_eq!(info.kind, PromType::Gauge);
    assert_eq!(info.samples[0].labels, labels(&[("service_name", "svc")]));
    assert_eq!(info.samples[0].value, 1.0);
    assert_eq!(families.len(), 4);

    let quiet = RenderOptions {
        target_info: false,
        scope_labels: false,
        ..opts
    };
    let families = families_from(&view, &quiet, false);
    assert!(families.iter().all(|f| f.name != "target_info"));
    assert_eq!(families[0].samples[0].labels, labels(&[("k", "v")]));
}

#[test]
fn target_info_needs_resource_labels_and_yields_to_an_instrument_of_that_name() {
    let empty = families_from(
        &one_scope(Vec::new()),
        &options("UnderscoreEscapingWithSuffixes"),
        false,
    );
    assert!(empty.is_empty());

    let mut view = one_scope(vec![metric(
        "target_info",
        "",
        Points::Gauge(vec![(labels(&[("mine", "1")]), 7.0)]),
    )]);
    view.attributes = labels(&[("service.name", "svc")]);
    let families = families_from(&view, &options("UnderscoreEscapingWithSuffixes"), false);
    assert_eq!(families.len(), 1);
    assert_eq!(families[0].samples.len(), 1);
    assert_eq!(families[0].samples[0].value, 7.0);
    assert_eq!(families[0].help, "");
}

#[test]
fn a_second_type_under_one_name_is_dropped() {
    let view = one_scope(vec![
        metric(
            "dup",
            "",
            Points::Sum {
                monotonic: false,
                points: vec![(Labels::new(), 1.0)],
            },
        ),
        metric(
            "dup",
            "",
            Points::Histogram(vec![HistogramPoint {
                attributes: Labels::new(),
                bounds: Vec::new(),
                bucket_counts: vec![1],
                count: 1,
                sum: 1.0,
            }]),
        ),
        metric("dup", "", Points::Gauge(vec![(Labels::new(), 2.0)])),
    ]);
    let families = families_from(&view, &options("UnderscoreEscapingWithoutSuffixes"), false);
    assert_eq!(families.len(), 1);
    assert_eq!(families[0].kind, PromType::Gauge);
    assert_eq!(
        families[0]
            .samples
            .iter()
            .map(|s| s.value)
            .collect::<Vec<_>>(),
        vec![1.0, 2.0]
    );
}

#[test]
fn utf8_names_need_negotiation() {
    let view = one_scope(vec![metric(
        "http.requests",
        "",
        Points::Sum {
            monotonic: true,
            points: vec![(labels(&[("http.route", "/a")]), 1.0)],
        },
    )]);
    let opts = options("NoUTF8EscapingWithSuffixes");
    let escaped = families_from(&view, &opts, false);
    assert_eq!(escaped[0].name, "http_requests_total");
    assert_eq!(
        escaped[0].samples[0].labels,
        labels(&[("http_route", "/a")])
    );
    let utf8 = families_from(&view, &opts, true);
    assert_eq!(utf8[0].name, "http.requests_total");
    assert_eq!(utf8[0].samples[0].labels, labels(&[("http.route", "/a")]));
}

#[test]
fn values_format_like_prometheus_expects() {
    assert_eq!(format_value(f64::NAN), "NaN");
    assert_eq!(format_value(f64::INFINITY), "+Inf");
    assert_eq!(format_value(f64::NEG_INFINITY), "-Inf");
    assert_eq!(format_value(0.0), "0");
    assert_eq!(format_value(1.0), "1");
    assert_eq!(format_value(-12.5), "-12.5");
    assert_eq!(format_value(1e-7), "0.0000001");
    assert_eq!(format_value(9.9e-8), "9.9e-8");
    assert_eq!(format_value(-9.9e-8), "-9.9e-8");
    assert_eq!(format_value(1e20), "100000000000000000000");
    assert_eq!(format_value(1e21), "1e21");
    assert_eq!(format_value(-1e21), "-1e21");
}

#[test]
fn rendering_writes_help_type_and_samples() {
    let mut counter = Family::new("requests_total", PromType::Counter, "Line\\one\ntwo");
    counter.push(labels(&[("route", "/a\"b\\c\nd")]), 3.0);
    counter.push(Labels::new(), 4.0);
    let mut gauge = Family::new("temp", PromType::Gauge, "");
    gauge.push(labels(&[("a", "1"), ("b", "2")]), 1.5);
    let mut histogram = Family::new("lat", PromType::Histogram, "");
    histogram.samples.push(Sample {
        suffix: "_count",
        labels: Labels::new(),
        value: 2.0,
    });
    let text = render(&[counter, gauge, histogram]);
    assert_eq!(
        text,
        "# HELP requests_total Line\\\\one\\ntwo\n\
         # TYPE requests_total counter\n\
         requests_total{route=\"/a\\\"b\\\\c\\nd\"} 3\n\
         requests_total 4\n\
         # TYPE temp gauge\n\
         temp{a=\"1\",b=\"2\"} 1.5\n\
         # TYPE lat histogram\n\
         lat_count 2\n"
    );
    assert_eq!(render(&[]), "");
}

#[test]
fn rendering_quotes_utf8_names_and_labels() {
    let mut family = Family::new("http.requests_total", PromType::Counter, "h");
    family.push(labels(&[("http.route", "/a"), ("plain", "x")]), 1.0);
    family.push(Labels::new(), 2.0);
    let mut colon = Family::new("a:b", PromType::Gauge, "");
    colon.push(labels(&[("a:b", "1")]), 1.0);
    let text = render(&[family, colon]);
    assert_eq!(
        text,
        "# HELP \"http.requests_total\" h\n\
         # TYPE \"http.requests_total\" counter\n\
         {\"http.requests_total\",\"http.route\"=\"/a\",plain=\"x\"} 1\n\
         {\"http.requests_total\"} 2\n\
         # TYPE a:b gauge\n\
         a:b{\"a:b\"=\"1\"} 1\n"
    );
}

#[test]
fn legacy_name_rules() {
    assert!(is_legacy_name("_a:b9"));
    assert!(is_legacy_name(":x"));
    assert!(!is_legacy_name(""));
    assert!(!is_legacy_name("9a"));
    assert!(!is_legacy_name("a.b"));
    assert!(is_legacy_label("_a9"));
    assert!(!is_legacy_label("a:b"));
    assert!(!is_legacy_label("9"));
}

#[test]
fn reader_metrics_named_like_a_health_family_are_skipped() {
    let view = one_scope(vec![
        metric(
            "provide_telemetry_setup_error",
            "",
            Points::Gauge(vec![(Labels::new(), 1.0)]),
        ),
        metric("kept", "", Points::Gauge(vec![(Labels::new(), 2.0)])),
    ]);
    let families = families_from(&view, &options("UnderscoreEscapingWithSuffixes"), false);
    let names: Vec<&str> = families.iter().map(|f| f.name.as_str()).collect();
    assert_eq!(names, vec!["kept"]);
}
