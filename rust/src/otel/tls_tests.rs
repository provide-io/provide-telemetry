// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use super::*;

use crate::test_certs::TestCerts;

#[mutants::skip] // test helper
fn path(p: &std::path::Path) -> Option<String> {
    Some(p.display().to_string())
}

#[test]
fn nothing_configured_means_no_tls() {
    assert_eq!(
        load_client_tls("metrics", &OtlpTlsConfig::default()).unwrap(),
        None
    );
}

#[test]
fn files_are_read_into_memory() {
    let certs = TestCerts::generate();
    let tls = OtlpTlsConfig {
        certificate: path(&certs.ca),
        client_certificate: path(&certs.client_cert),
        client_key: path(&certs.client_key),
    };
    let loaded = load_client_tls("metrics", &tls).unwrap().unwrap();
    assert_eq!(loaded.ca, Some(std::fs::read(&certs.ca).unwrap()));
    assert_eq!(
        loaded.identity,
        Some((
            std::fs::read(&certs.client_cert).unwrap(),
            std::fs::read(&certs.client_key).unwrap()
        ))
    );
    assert!(http_client("metrics", &loaded, Duration::from_secs(1)).is_ok());

    let ca_only = OtlpTlsConfig {
        certificate: path(&certs.ca),
        ..OtlpTlsConfig::default()
    };
    let loaded = load_client_tls("logs", &ca_only).unwrap().unwrap();
    assert_eq!(loaded.identity, None);
    assert!(http_client("logs", &loaded, Duration::from_secs(1)).is_ok());

    let identity_only = OtlpTlsConfig {
        client_certificate: path(&certs.client_cert),
        client_key: path(&certs.client_key),
        ..OtlpTlsConfig::default()
    };
    let loaded = load_client_tls("traces", &identity_only).unwrap().unwrap();
    assert_eq!(loaded.ca, None);
    assert!(http_client("traces", &loaded, Duration::from_secs(1)).is_ok());
}

#[test]
fn unreadable_or_unpaired_files_are_errors() {
    let missing = OtlpTlsConfig {
        certificate: Some("/nonexistent/ca.crt".to_string()),
        ..OtlpTlsConfig::default()
    };
    let err = load_client_tls("metrics", &missing).unwrap_err();
    assert!(
        err.message
            .starts_with("OTLP metrics TLS: cannot read certificate /nonexistent/ca.crt: "),
        "{}",
        err.message
    );

    let certs = TestCerts::generate();
    let missing_key = OtlpTlsConfig {
        client_certificate: path(&certs.client_cert),
        client_key: Some("/nonexistent/client.key".to_string()),
        ..OtlpTlsConfig::default()
    };
    let err = load_client_tls("logs", &missing_key).unwrap_err();
    assert!(err
        .message
        .contains("cannot read client key /nonexistent/client.key"));
    let missing_cert = OtlpTlsConfig {
        client_certificate: Some("/nonexistent/client.crt".to_string()),
        client_key: path(&certs.client_key),
        ..OtlpTlsConfig::default()
    };
    let err = load_client_tls("logs", &missing_cert).unwrap_err();
    assert!(err
        .message
        .contains("cannot read client certificate /nonexistent/client.crt"));

    for unpaired in [
        OtlpTlsConfig {
            client_certificate: path(&certs.client_cert),
            ..OtlpTlsConfig::default()
        },
        OtlpTlsConfig {
            client_key: path(&certs.client_key),
            ..OtlpTlsConfig::default()
        },
    ] {
        let err = load_client_tls("traces", &unpaired).unwrap_err();
        assert_eq!(
            err.message,
            "OTLP traces TLS: a client certificate and a client key must be set together"
        );
    }
}

#[test]
fn unusable_pem_is_an_error() {
    let no_certificate = ClientTls {
        ca: Some(b"not a pem file".to_vec()),
        identity: None,
    };
    let err = http_client("metrics", &no_certificate, Duration::from_secs(1)).unwrap_err();
    assert_eq!(
        err.message,
        "OTLP metrics TLS: the CA certificate file holds no certificate"
    );

    let bad_identity = ClientTls {
        ca: None,
        identity: Some((b"junk".to_vec(), b"junk".to_vec())),
    };
    let err = http_client("metrics", &bad_identity, Duration::from_secs(1)).unwrap_err();
    assert!(
        err.message.starts_with("OTLP metrics TLS: "),
        "{}",
        err.message
    );

    let broken_pem = ClientTls {
        ca: Some(b"-----BEGIN CERTIFICATE-----\n!!!\n-----END CERTIFICATE-----\n".to_vec()),
        identity: None,
    };
    let err = http_client("metrics", &broken_pem, Duration::from_secs(1)).unwrap_err();
    assert!(
        err.message.starts_with("OTLP metrics TLS: "),
        "{}",
        err.message
    );
}

#[cfg(feature = "otel-grpc")]
#[test]
fn tonic_tls_carries_the_ca_and_identity() {
    let certs = TestCerts::generate();
    let full = ClientTls {
        ca: Some(std::fs::read(&certs.ca).unwrap()),
        identity: Some((
            std::fs::read(&certs.client_cert).unwrap(),
            std::fs::read(&certs.client_key).unwrap(),
        )),
    };
    let rendered = format!("{:?}", tonic_tls(&full));
    assert!(rendered.contains("certs: [Certificate"), "{rendered}");
    assert!(rendered.contains("identity: Some"), "{rendered}");
    let empty = format!(
        "{:?}",
        tonic_tls(&ClientTls {
            ca: None,
            identity: None
        })
    );
    assert!(empty.contains("certs: []"), "{empty}");
    assert!(!empty.contains("identity: Some"), "{empty}");
}

#[mutants::skip] // test helper
fn tls_config(protocol: &str, tls: &OtlpTlsConfig) -> crate::config::TelemetryConfig {
    let mut config = crate::config::TelemetryConfig::default();
    for (endpoint, signal_protocol, signal_tls) in [
        (
            &mut config.logging.otlp_endpoint,
            &mut config.logging.otlp_protocol,
            &mut config.logging.otlp_tls,
        ),
        (
            &mut config.tracing.otlp_endpoint,
            &mut config.tracing.otlp_protocol,
            &mut config.tracing.otlp_tls,
        ),
        (
            &mut config.metrics.otlp_endpoint,
            &mut config.metrics.otlp_protocol,
            &mut config.metrics.otlp_tls,
        ),
    ] {
        *endpoint = Some("https://127.0.0.1:9/v1/x".to_string());
        *signal_protocol = protocol.to_string();
        *signal_tls = tls.clone();
    }
    config.exporter.logs_shutdown_timeout_seconds = 1.0;
    config
}

#[test]
fn every_exporter_is_built_with_the_configured_tls() {
    let _guard = crate::testing::acquire_test_state_lock();
    crate::testing::reset_telemetry_state();
    let certs = TestCerts::generate();
    let tls = OtlpTlsConfig {
        certificate: path(&certs.ca),
        client_certificate: path(&certs.client_cert),
        client_key: path(&certs.client_key),
    };
    // gRPC builds need the caller's Tokio runtime; each signal's tests cover it.
    for protocol in ["http/protobuf", "http/json"] {
        crate::setup_telemetry(Some(tls_config(protocol, &tls))).expect("setup");
        let owned = crate::otel::owned_signals();
        assert!(owned.logs && owned.traces && owned.metrics, "{protocol}");
        assert_eq!(crate::health::get_health_snapshot().setup_error, None);
        crate::shutdown_telemetry(Some(1.0)).expect("shutdown");
    }
    crate::testing::reset_telemetry_state();
}

#[test]
fn an_unreadable_certificate_leaves_the_exporter_uninstalled_and_records_setup_error() {
    let _guard = crate::testing::acquire_test_state_lock();
    crate::testing::reset_telemetry_state();
    let tls = OtlpTlsConfig {
        certificate: Some("/nonexistent/ca.crt".to_string()),
        ..OtlpTlsConfig::default()
    };
    crate::setup_telemetry(Some(tls_config("http/protobuf", &tls))).expect("fail open");
    let owned = crate::otel::owned_signals();
    assert!(!owned.logs && !owned.traces && !owned.metrics);
    let error = crate::health::get_health_snapshot().setup_error.unwrap();
    assert!(error.starts_with("OTLP "), "{error}");
    assert!(
        error.contains("cannot read certificate /nonexistent/ca.crt"),
        "{error}"
    );
    crate::shutdown_telemetry(None).expect("shutdown");

    let mut strict = tls_config("http/protobuf", &tls);
    strict.exporter.traces_fail_open = false;
    let err = crate::setup_telemetry(Some(strict)).unwrap_err();
    assert!(
        err.message
            .starts_with("OTLP traces TLS: cannot read certificate"),
        "{}",
        err.message
    );
    crate::testing::reset_telemetry_state();
}
