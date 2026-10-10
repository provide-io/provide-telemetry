// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! OTEL_EXPORTER_OTLP_{CERTIFICATE,CLIENT_CERTIFICATE,CLIENT_KEY} and their
//! per-signal forms, per-signal winning (prometheus_metrics.push_security).

use std::collections::HashMap;

use provide_telemetry::{OtlpTlsConfig, TelemetryConfig};

fn parse(pairs: &[(&str, &str)]) -> TelemetryConfig {
    let env: HashMap<String, String> = pairs
        .iter()
        .map(|(k, v)| ((*k).to_string(), (*v).to_string()))
        .collect();
    TelemetryConfig::from_map(&env).expect("valid env")
}

#[test]
fn unset_means_no_tls_files() {
    let config = parse(&[]);
    for tls in [
        &config.logging.otlp_tls,
        &config.tracing.otlp_tls,
        &config.metrics.otlp_tls,
    ] {
        assert_eq!(tls, &OtlpTlsConfig::default());
    }
}

#[test]
fn shared_values_apply_to_every_signal_and_per_signal_values_win() {
    let config = parse(&[
        ("OTEL_EXPORTER_OTLP_CERTIFICATE", " /shared/ca.crt "),
        (
            "OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE",
            "/shared/client.crt",
        ),
        ("OTEL_EXPORTER_OTLP_CLIENT_KEY", "/shared/client.key"),
        ("OTEL_EXPORTER_OTLP_METRICS_CERTIFICATE", "/metrics/ca.crt"),
        (
            "OTEL_EXPORTER_OTLP_TRACES_CLIENT_CERTIFICATE",
            "/traces/client.crt",
        ),
        ("OTEL_EXPORTER_OTLP_LOGS_CLIENT_KEY", "/logs/client.key"),
        // An empty per-signal value counts as unset.
        ("OTEL_EXPORTER_OTLP_LOGS_CERTIFICATE", " "),
    ]);
    let shared = |path: &str| Some(format!("/shared/{path}"));
    assert_eq!(
        config.logging.otlp_tls,
        OtlpTlsConfig {
            certificate: shared("ca.crt"),
            client_certificate: shared("client.crt"),
            client_key: Some("/logs/client.key".to_string()),
        }
    );
    assert_eq!(
        config.tracing.otlp_tls,
        OtlpTlsConfig {
            certificate: shared("ca.crt"),
            client_certificate: Some("/traces/client.crt".to_string()),
            client_key: shared("client.key"),
        }
    );
    assert_eq!(
        config.metrics.otlp_tls,
        OtlpTlsConfig {
            certificate: Some("/metrics/ca.crt".to_string()),
            client_certificate: shared("client.crt"),
            client_key: shared("client.key"),
        }
    );
}
