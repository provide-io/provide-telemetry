// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Unit cases for the Prometheus settings. The shared fixture cases
//! (exporter_selection, listener_path, listener_port, translation_strategy)
//! run in `tests/prometheus_config_fixtures.rs`.

use super::*;

fn exporters(raw: Option<&str>) -> Vec<String> {
    let (exporters, warnings) = parse_exporters(raw, false).unwrap();
    assert!(warnings.is_empty(), "{raw:?}: {warnings:?}");
    exporters
}

#[test]
fn exporters_default_trim_lowercase_and_drop_empty_entries() {
    assert_eq!(exporters(None), vec!["otlp"]);
    assert_eq!(exporters(Some(" , ")), vec!["otlp"]);
    assert_eq!(
        exporters(Some(" OTLP ,, Prometheus ")),
        vec!["otlp", "prometheus"]
    );
    assert!(exporters(Some("none")).is_empty());
    assert!(exporters(Some("NONE,")).is_empty());
    assert!(exporters(Some("none,none")).is_empty());
    assert_eq!(exporters(Some("otlp,otlp")), vec!["otlp", "otlp"]);
}

const UNKNOWN: &str = "OTEL_METRICS_EXPORTER: unknown exporter statsd, ignored";
const CONSOLE: &str =
    "OTEL_METRICS_EXPORTER: console is not supported by provide-telemetry, ignored";
const LOGGING: &str =
    "OTEL_METRICS_EXPORTER: logging is not supported by provide-telemetry, ignored";
const NONE_MIXED: &str =
    "OTEL_METRICS_EXPORTER: none cannot be combined with other exporters, ignored";
const FALLBACK: &str = "OTEL_METRICS_EXPORTER: no supported exporter left, using otlp";

#[test]
fn unusable_entries_are_warned_about_and_ignored() {
    let cases: [(&str, Vec<&str>, Vec<&str>); 6] = [
        ("otlp,statsd", vec!["otlp"], vec![UNKNOWN]),
        (
            "statsd,prometheus,STATSD",
            vec!["prometheus"],
            vec![UNKNOWN],
        ),
        ("console", vec!["otlp"], vec![CONSOLE, FALLBACK]),
        ("logging,prometheus", vec!["prometheus"], vec![LOGGING]),
        ("prometheus,none", vec!["prometheus"], vec![NONE_MIXED]),
        (
            "none,console,statsd",
            vec!["otlp"],
            vec![CONSOLE, UNKNOWN, NONE_MIXED, FALLBACK],
        ),
    ];
    for (raw, want_exporters, want_warnings) in cases {
        let (got, warnings) = parse_exporters(Some(raw), false).unwrap();
        assert_eq!(got, want_exporters, "{raw}");
        assert_eq!(warnings, want_warnings, "{raw}");
    }
}

#[test]
fn strict_turns_warnings_into_an_error() {
    let err = parse_exporters(Some("otlp,statsd"), true).unwrap_err();
    assert_eq!(
        err.message,
        format!("PROVIDE_TELEMETRY_STRICT_CONFIG: {UNKNOWN}")
    );
    let err = parse_exporters(Some("none,console"), true).unwrap_err();
    assert_eq!(
        err.message,
        format!("PROVIDE_TELEMETRY_STRICT_CONFIG: {CONSOLE}; {NONE_MIXED}; {FALLBACK}")
    );
    assert_eq!(
        parse_exporters(Some("prometheus"), true).unwrap(),
        (vec!["prometheus".to_string()], Vec::new())
    );
    assert_eq!(
        parse_exporters(Some("none"), true).unwrap(),
        (Vec::new(), Vec::new())
    );
}

#[test]
fn setup_problems_put_ignored_entries_before_tls() {
    let warnings = vec![UNKNOWN.to_string(), FALLBACK.to_string()];
    assert_eq!(setup_problems(&[], None), None);
    assert_eq!(
        setup_problems(&[], Some("tls".to_string())),
        Some("tls".to_string())
    );
    assert_eq!(
        setup_problems(&warnings, None),
        Some(format!("{UNKNOWN}; {FALLBACK}"))
    );
    assert_eq!(
        setup_problems(&warnings, Some("tls".to_string())),
        Some(format!("{UNKNOWN}; {FALLBACK}; tls"))
    );
}

#[test]
fn validate_exporters_accepts_known_names_only() {
    assert!(validate_exporters(&[]).is_ok());
    assert!(validate_exporters(&["otlp".to_string(), "prometheus".to_string()]).is_ok());
    let err = validate_exporters(&["none".to_string()]).unwrap_err();
    assert_eq!(err.message, "metrics exporters: unknown \"none\"");
}

#[test]
fn port_parses_the_full_range_and_rejects_the_rest() {
    assert_eq!(parse_port(None).unwrap(), 9464);
    assert_eq!(parse_port(Some("  ")).unwrap(), 9464);
    assert_eq!(parse_port(Some(" 0 ")).unwrap(), 0);
    assert_eq!(parse_port(Some("65535")).unwrap(), 65535);
    let err = parse_port(Some("65536")).unwrap_err();
    assert_eq!(
        err.message,
        "OTEL_EXPORTER_PROMETHEUS_PORT: want an integer in 0-65535, got \"65536\""
    );
}

#[test]
fn listen_path_and_translation_are_validated() {
    let ok = PrometheusConfig::default();
    assert!(ok.validate().is_ok());

    let listen = PrometheusConfig {
        listen: "sometimes".to_string(),
        ..PrometheusConfig::default()
    };
    assert_eq!(
        listen.validate().unwrap_err().message,
        "PROVIDE_METRICS_PROMETHEUS_LISTEN: want false, true or auto, got \"sometimes\""
    );

    for bad in ["metrics", "/m?x=1", "/m#a"] {
        let path = PrometheusConfig {
            path: bad.to_string(),
            ..PrometheusConfig::default()
        };
        assert_eq!(
            path.validate().unwrap_err().message,
            format!(
                "PROVIDE_METRICS_PROMETHEUS_PATH: want a path starting with / and no query or fragment, got {bad:?}"
            )
        );
    }

    let translation = PrometheusConfig {
        translation: "Legacy".to_string(),
        ..PrometheusConfig::default()
    };
    assert_eq!(
        translation.validate().unwrap_err().message,
        "PROVIDE_METRICS_PROMETHEUS_TRANSLATION: unknown strategy \"Legacy\""
    );
    for strategy in TRANSLATION_STRATEGIES {
        let named = PrometheusConfig {
            translation: strategy.to_string(),
            ..PrometheusConfig::default()
        };
        assert!(named.validate().is_ok());
    }
}

#[test]
fn defaults_match_the_spec() {
    let config = PrometheusConfig::default();
    assert_eq!(config.listen, "false");
    assert_eq!(config.host, "127.0.0.1");
    assert_eq!(config.port, 9464);
    assert_eq!(config.path, "/metrics");
    assert_eq!(config.translation, "UnderscoreEscapingWithSuffixes");
    assert!(!config.scope_labels);
    assert!(config.target_info);
    assert_eq!(config.web_config, "");
}

#[test]
fn raw_values_are_trimmed_lowercased_and_validated() {
    let parsed = RawPrometheus {
        listen: Some(" AUTO "),
        host: Some(" 0.0.0.0 "),
        port: Some("9100"),
        path: Some(" /internal "),
        translation: Some("NoTranslation"),
        scope_labels: true,
        target_info: false,
        web_config: Some(" web.yml "),
    }
    .parse()
    .unwrap();
    assert_eq!(
        parsed,
        PrometheusConfig {
            listen: "auto".to_string(),
            host: "0.0.0.0".to_string(),
            port: 9100,
            path: "/internal".to_string(),
            translation: "NoTranslation".to_string(),
            scope_labels: true,
            target_info: false,
            web_config: "web.yml".to_string(),
        }
    );

    let unset = RawPrometheus {
        listen: None,
        host: Some(""),
        port: None,
        path: Some(""),
        translation: None,
        scope_labels: false,
        target_info: true,
        web_config: None,
    }
    .parse()
    .unwrap();
    assert_eq!(unset, PrometheusConfig::default());

    let invalid = RawPrometheus {
        listen: Some("maybe"),
        host: None,
        port: None,
        path: None,
        translation: None,
        scope_labels: false,
        target_info: true,
        web_config: None,
    }
    .parse();
    assert!(invalid.is_err());
}

#[test]
fn env_str_trims_and_defaults() {
    assert_eq!(env_str(None, "d"), "d");
    assert_eq!(env_str(Some("   "), "d"), "d");
    assert_eq!(env_str(Some(" v "), "d"), "v");
}
