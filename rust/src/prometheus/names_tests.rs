// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Every metric_names, translation_corpus, translator_only_corpus, label_names
//! and label_corpus case in spec/prometheus_fixtures.yaml, read from the file.

use super::*;

use serde_yaml::Value;

const STRATEGIES: [&str; 4] = [
    "UnderscoreEscapingWithSuffixes",
    "UnderscoreEscapingWithoutSuffixes",
    "NoUTF8EscapingWithSuffixes",
    "NoTranslation",
];

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
fn kind_of(instrument: &str) -> Kind {
    match instrument {
        "counter" | "observable_counter" => Kind::MonotonicCounter,
        "observable_up_down_counter" => Kind::NonMonotonicCounter,
        "gauge" | "observable_gauge" => Kind::Gauge,
        "histogram" => Kind::Histogram,
        other => panic!("unknown instrument {other}"),
    }
}

#[mutants::skip] // test helper
fn check_metric_section(section: &str) -> usize {
    let doc = fixtures();
    let cases = doc[section].as_sequence().expect("section is a list");
    let mut checked = 0;
    for case in cases {
        let name = case["name"].as_str().unwrap();
        let unit = case["unit"].as_str().unwrap();
        let kind = kind_of(case["instrument"].as_str().unwrap());
        for strategy in STRATEGIES {
            let expected = case["expected"][strategy].as_str().map(str::to_string);
            let got = metric_name(name, unit, kind, Strategy::named(strategy));
            assert_eq!(
                got, expected,
                "{section}: {name:?} unit {unit:?} {kind:?} under {strategy}"
            );
            checked += 1;
        }
    }
    checked
}

#[mutants::skip] // test helper
fn check_label_section(section: &str) -> usize {
    let doc = fixtures();
    let cases = doc[section].as_sequence().expect("section is a list");
    for case in cases {
        let attribute = case["attribute"].as_str().unwrap();
        let escaped = case["escaped"].as_str().map(str::to_string);
        let utf8 = case["utf8"].as_str().map(str::to_string);
        assert_eq!(
            label_name(attribute, Strategy::named("UnderscoreEscapingWithSuffixes")),
            escaped,
            "{section}: escaped {attribute:?}"
        );
        assert_eq!(
            label_name(attribute, Strategy::named("NoTranslation")),
            utf8,
            "{section}: utf8 {attribute:?}"
        );
    }
    cases.len()
}

#[test]
fn metric_names_match_the_reference() {
    assert!(check_metric_section("metric_names") >= 40);
}

#[test]
fn translation_corpus_matches_the_reference() {
    assert!(check_metric_section("translation_corpus") > 100);
}

#[test]
fn translator_only_corpus_matches_the_reference() {
    assert!(check_metric_section("translator_only_corpus") > 100);
}

#[test]
fn label_names_match_the_reference() {
    assert_eq!(check_label_section("label_names"), 6);
}

#[test]
fn label_corpus_matches_the_reference() {
    assert!(check_label_section("label_corpus") >= 20);
}

#[test]
fn strategy_names_decide_escaping_and_suffixes() {
    assert_eq!(
        Strategy::named("UnderscoreEscapingWithSuffixes"),
        Strategy {
            escapes: true,
            suffixes: true
        }
    );
    assert_eq!(
        Strategy::named("NoTranslation"),
        Strategy {
            escapes: false,
            suffixes: false
        }
    );
}

#[test]
fn every_mapped_unit_is_spelled_out() {
    let s = Strategy::named("UnderscoreEscapingWithSuffixes");
    let cases = [
        ("d", "days"),
        ("h", "hours"),
        ("min", "minutes"),
        ("s", "seconds"),
        ("ms", "milliseconds"),
        ("us", "microseconds"),
        ("ns", "nanoseconds"),
        ("By", "bytes"),
        ("KiBy", "kibibytes"),
        ("MiBy", "mebibytes"),
        ("GiBy", "gibibytes"),
        ("TiBy", "tibibytes"),
        ("KBy", "kilobytes"),
        ("MBy", "megabytes"),
        ("GBy", "gigabytes"),
        ("TBy", "terabytes"),
        ("m", "meters"),
        ("V", "volts"),
        ("A", "amperes"),
        ("J", "joules"),
        ("W", "watts"),
        ("g", "grams"),
        ("Cel", "celsius"),
        ("Hz", "hertz"),
        ("%", "percent"),
        ("furlong", "furlong"),
    ];
    for (unit, word) in cases {
        assert_eq!(
            metric_name("x", unit, Kind::Gauge, s).as_deref(),
            Some(format!("x_{word}").as_str()),
            "unit {unit}"
        );
    }
    let per = [
        ("s", "second"),
        ("m", "minute"),
        ("h", "hour"),
        ("d", "day"),
        ("w", "week"),
        ("mo", "month"),
        ("y", "year"),
        ("fortnight", "fortnight"),
    ];
    for (unit, word) in per {
        assert_eq!(
            metric_name("x", &format!("By/{unit}"), Kind::Gauge, s).as_deref(),
            Some(format!("x_bytes_per_{word}").as_str()),
            "per unit {unit}"
        );
    }
}

#[test]
fn utf8_suffix_trimming_counts_characters_not_bytes() {
    let s = Strategy::named("NoUTF8EscapingWithSuffixes");
    // "é" is two bytes; trimming must drop it as one delimiter character.
    assert_eq!(
        metric_name("aaéseconds", "s", Kind::Gauge, s).as_deref(),
        Some("aaéseconds")
    );
    assert_eq!(
        metric_name("aétotal", "", Kind::MonotonicCounter, s).as_deref(),
        Some("a_total")
    );
    assert_eq!(
        metric_name("étotal", "", Kind::MonotonicCounter, s).as_deref(),
        Some("étotal_total")
    );
}

#[test]
fn per_unit_trimming_and_curly_annotations() {
    let s = Strategy::named("UnderscoreEscapingWithSuffixes");
    assert_eq!(
        metric_name("rate", " {req} / s ", Kind::Gauge, s).as_deref(),
        Some("rate_per_second")
    );
    assert_eq!(
        metric_name("rate", "By/{x}", Kind::Gauge, s).as_deref(),
        Some("rate_bytes")
    );
    assert_eq!(
        metric_name("bytes.rate", "By/s", Kind::Gauge, s).as_deref(),
        Some("bytes_rate_per_second")
    );
    assert_eq!(
        metric_name("x", "_a_/_b_", Kind::Gauge, s).as_deref(),
        Some("x_a_per_b")
    );
    assert_eq!(
        metric_name("x", "a/-", Kind::Gauge, s).as_deref(),
        Some("x_a")
    );
}

#[test]
fn reserved_labels_keep_their_underscores() {
    let s = Strategy::named("UnderscoreEscapingWithSuffixes");
    assert_eq!(label_name("__a.b__", s).as_deref(), Some("__a_b__"));
    assert_eq!(label_name("__9__", s).as_deref(), Some("__9__"));
    assert_eq!(label_name("9", s).as_deref(), Some("key_9"));
    assert_eq!(label_name("", s), None);
}
