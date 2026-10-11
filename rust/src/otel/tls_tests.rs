// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! prometheus_metrics.push_security: the OTLP TLS variables, per-signal
//! winning, and files that cannot be read or loaded.

use super::*;

use crate::test_certs::{EnvGuard, TestCerts};
use crate::testing::{acquire_test_state_lock, reset_telemetry_state};

const MISSING: &str = "/nonexistent/provide.pem";

#[test]
fn nothing_configured_means_no_tls() {
    let _guard = acquire_test_state_lock();
    assert!(client_tls("METRICS").unwrap().is_none());
    assert!(ready("METRICS"));
    assert_eq!(take_problems(), None);
}

#[test]
fn files_load_and_per_signal_values_win() {
    let _guard = acquire_test_state_lock();
    let certs = TestCerts::generate();
    let mut env = EnvGuard::default();
    env.set("OTEL_EXPORTER_OTLP_CERTIFICATE", MISSING);
    env.set("OTEL_EXPORTER_OTLP_METRICS_CERTIFICATE", &certs.ca);
    env.set("OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE", &certs.client_cert);
    env.set("OTEL_EXPORTER_OTLP_CLIENT_KEY", &certs.client_key);
    let tls = client_tls("METRICS").unwrap().unwrap();
    assert_eq!(
        tls.ca.as_ref().unwrap().0,
        std::fs::read(&certs.ca).unwrap()
    );
    let (cert, key, _) = tls.identity.as_ref().unwrap();
    assert_eq!(cert, &std::fs::read(&certs.client_cert).unwrap());
    assert_eq!(key, &std::fs::read(&certs.client_key).unwrap());
    assert!(http_client(&tls, Duration::from_secs(1)).is_ok());
    assert!(ready("METRICS"));
    // The shared CA is still the bad one for every other signal.
    assert!(!ready("LOGS"));
    assert_eq!(
        take_problems().as_deref(),
        Some("OTEL_EXPORTER_OTLP_CERTIFICATE=/nonexistent/provide.pem: No such file or directory")
    );

    // A blank per-signal value falls back to the shared one.
    env.set("OTEL_EXPORTER_OTLP_CERTIFICATE", &certs.ca);
    env.set("OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE", "  ");
    let tls = client_tls("TRACES").unwrap().unwrap();
    assert!(tls.ca.is_some());
    assert!(exporter_tls("TRACES").unwrap().is_some());
}

#[test]
fn a_ca_or_an_identity_alone_is_enough() {
    let _guard = acquire_test_state_lock();
    let certs = TestCerts::generate();
    let mut env = EnvGuard::default();
    env.set("OTEL_EXPORTER_OTLP_LOGS_CERTIFICATE", &certs.ca);
    let ca_only = client_tls("LOGS").unwrap().unwrap();
    assert!(ca_only.identity.is_none());
    assert!(http_client(&ca_only, Duration::from_secs(1)).is_ok());

    env.set(
        "OTEL_EXPORTER_OTLP_TRACES_CLIENT_CERTIFICATE",
        &certs.client_cert,
    );
    env.set("OTEL_EXPORTER_OTLP_TRACES_CLIENT_KEY", &certs.client_key);
    let identity_only = client_tls("TRACES").unwrap().unwrap();
    assert!(identity_only.ca.is_none());
    assert!(http_client(&identity_only, Duration::from_secs(1)).is_ok());

    // A certificate without its key configures no identity.
    env.set(
        "OTEL_EXPORTER_OTLP_METRICS_CLIENT_CERTIFICATE",
        &certs.client_cert,
    );
    assert!(client_tls("METRICS").unwrap().is_none());
}

#[test]
fn each_unreadable_variable_is_named_with_its_path() {
    let _guard = acquire_test_state_lock();
    for kind in ["CERTIFICATE", "CLIENT_CERTIFICATE", "CLIENT_KEY"] {
        for name in [
            format!("OTEL_EXPORTER_OTLP_{kind}"),
            format!("OTEL_EXPORTER_OTLP_LOGS_{kind}"),
        ] {
            let mut env = EnvGuard::default();
            env.set(&name, MISSING);
            assert_eq!(
                client_tls("LOGS").unwrap_err(),
                format!("{name}={MISSING}: No such file or directory")
            );
            assert_eq!(
                exporter_tls("LOGS").unwrap_err().message,
                format!("{name}={MISSING}: No such file or directory")
            );
        }
    }
}

#[test]
fn files_that_do_not_load_are_reported() {
    let _guard = acquire_test_state_lock();
    let certs = TestCerts::generate();
    let junk = certs.dir.join("junk.pem");
    std::fs::write(&junk, "not a certificate\n").unwrap();
    let mut env = EnvGuard::default();
    env.set("OTEL_EXPORTER_OTLP_CERTIFICATE", &junk);
    assert_eq!(
        client_tls("METRICS").unwrap_err(),
        format!(
            "OTEL_EXPORTER_OTLP_CERTIFICATE={}: no PEM certificates",
            junk.display()
        )
    );

    drop(env);
    let mut env = EnvGuard::default();
    // The server's key does not belong to the client certificate.
    env.set("OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE", &certs.client_cert);
    env.set("OTEL_EXPORTER_OTLP_CLIENT_KEY", &certs.key);
    let err = client_tls("METRICS").unwrap_err();
    let prefix = format!(
        "OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE={}, OTEL_EXPORTER_OTLP_CLIENT_KEY={}: ",
        certs.client_cert.display(),
        certs.key.display()
    );
    assert!(
        err.starts_with(&prefix) && err.len() > prefix.len(),
        "{err}"
    );

    env.set("OTEL_EXPORTER_OTLP_CLIENT_KEY", &junk);
    let err = client_tls("METRICS").unwrap_err();
    assert!(err.contains(", OTEL_EXPORTER_OTLP_CLIENT_KEY="), "{err}");
    drop(env);
}

#[test]
fn problems_are_joined_and_cleared() {
    let _guard = acquire_test_state_lock();
    let mut env = EnvGuard::default();
    env.set("OTEL_EXPORTER_OTLP_LOGS_CLIENT_KEY", MISSING);
    env.set("OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE", MISSING);
    assert!(!ready("LOGS"));
    assert!(!ready("TRACES"));
    assert_eq!(
        take_problems().as_deref(),
        Some(
            "OTEL_EXPORTER_OTLP_LOGS_CLIENT_KEY=/nonexistent/provide.pem: No such file or directory; \
             OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE=/nonexistent/provide.pem: No such file or directory"
        )
    );
    assert_eq!(take_problems(), None);
}

#[test]
fn io_reasons_drop_the_os_error_number() {
    let missing = std::fs::read(MISSING).unwrap_err();
    assert_eq!(io_reason(&missing), "No such file or directory");
    let plain = std::io::Error::other("plain reason");
    assert_eq!(io_reason(&plain), "plain reason");
}

#[cfg(feature = "otel-grpc")]
#[test]
fn tonic_tls_carries_the_ca_and_identity() {
    let _guard = acquire_test_state_lock();
    let certs = TestCerts::generate();
    let mut env = EnvGuard::default();
    env.set("OTEL_EXPORTER_OTLP_CERTIFICATE", &certs.ca);
    env.set("OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE", &certs.client_cert);
    env.set("OTEL_EXPORTER_OTLP_CLIENT_KEY", &certs.client_key);
    let full = client_tls("LOGS").unwrap().unwrap();
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
fn otlp_config(protocol: &str) -> crate::config::TelemetryConfig {
    let mut config = crate::config::TelemetryConfig::default();
    for (endpoint, signal_protocol) in [
        (
            &mut config.logging.otlp_endpoint,
            &mut config.logging.otlp_protocol,
        ),
        (
            &mut config.tracing.otlp_endpoint,
            &mut config.tracing.otlp_protocol,
        ),
        (
            &mut config.metrics.otlp_endpoint,
            &mut config.metrics.otlp_protocol,
        ),
    ] {
        *endpoint = Some("https://127.0.0.1:9/v1/x".to_string());
        *signal_protocol = protocol.to_string();
    }
    config.exporter.logs_shutdown_timeout_seconds = 1.0;
    config
}

#[test]
fn every_exporter_is_built_with_the_configured_tls() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    let certs = TestCerts::generate();
    let mut env = EnvGuard::default();
    env.set("OTEL_EXPORTER_OTLP_CERTIFICATE", &certs.ca);
    env.set("OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE", &certs.client_cert);
    env.set("OTEL_EXPORTER_OTLP_CLIENT_KEY", &certs.client_key);
    // gRPC builds need the caller's Tokio runtime; each signal's tests cover it.
    for protocol in ["http/protobuf", "http/json"] {
        crate::setup_telemetry(Some(otlp_config(protocol))).expect("setup");
        let owned = crate::otel::owned_signals();
        assert!(owned.logs && owned.traces && owned.metrics, "{protocol}");
        assert_eq!(crate::health::get_health_snapshot().setup_error, None);
        crate::shutdown_telemetry(Some(1.0)).expect("shutdown");
    }
    reset_telemetry_state();
}

#[test]
fn an_unloadable_file_skips_the_exporter_records_setup_error_and_never_fails_setup() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    let mut env = EnvGuard::default();
    env.set("OTEL_EXPORTER_OTLP_CERTIFICATE", MISSING);
    let mut config = otlp_config("http/protobuf");
    // Even fail-closed exporters do not fail setup over a TLS file.
    config.exporter.logs_fail_open = false;
    config.exporter.traces_fail_open = false;
    config.exporter.metrics_fail_open = false;
    config.metrics.exporters = vec!["otlp".to_string(), "prometheus".to_string()];
    crate::setup_telemetry(Some(config)).expect("a TLS problem never fails setup");
    let owned = crate::otel::owned_signals();
    assert!(!owned.logs && !owned.traces);
    // Metrics keep the pull reader; only the OTLP reader is skipped.
    assert_eq!(crate::prometheus::metrics_handler("GET", None).status, 200);
    let reason =
        "OTEL_EXPORTER_OTLP_CERTIFICATE=/nonexistent/provide.pem: No such file or directory";
    assert_eq!(
        crate::health::get_health_snapshot().setup_error,
        Some(format!("{reason}; {reason}; {reason}"))
    );
    reset_telemetry_state();
}
