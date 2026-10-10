// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Client TLS for the OTLP exporters: a private CA and mutual TLS from
//! `OTEL_EXPORTER_OTLP_{,LOGS_,TRACES_,METRICS_}{CERTIFICATE,CLIENT_CERTIFICATE,CLIENT_KEY}`.
//!
//! See `prometheus_metrics.push_security` in `spec/telemetry-api.yaml`. A file
//! that is named but cannot be read or parsed is an exporter build error, never
//! silently replaced by the system trust store. A configured CA replaces the
//! built-in roots, as the other SDKs' exporters do.

use std::time::Duration;

use crate::config::OtlpTlsConfig;
use crate::errors::TelemetryError;

/// The PEM bytes one signal's exporter trusts and presents.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct ClientTls {
    pub(super) ca: Option<Vec<u8>>,
    /// (certificate, key) for mutual TLS.
    pub(super) identity: Option<(Vec<u8>, Vec<u8>)>,
}

fn read(signal: &str, what: &str, path: &str) -> Result<Vec<u8>, TelemetryError> {
    std::fs::read(path).map_err(|err| {
        TelemetryError::new(format!("OTLP {signal} TLS: cannot read {what} {path}: {err}"))
    })
}

/// Read the files `tls` names; `None` when it names none.
pub(super) fn load_client_tls(
    signal: &str,
    tls: &OtlpTlsConfig,
) -> Result<Option<ClientTls>, TelemetryError> {
    let ca = match &tls.certificate {
        Some(path) => Some(read(signal, "certificate", path)?),
        None => None,
    };
    let identity = match (&tls.client_certificate, &tls.client_key) {
        (None, None) => None,
        (Some(cert), Some(key)) => Some((
            read(signal, "client certificate", cert)?,
            read(signal, "client key", key)?,
        )),
        _ => {
            return Err(TelemetryError::new(format!(
                "OTLP {signal} TLS: a client certificate and a client key must be set together"
            )))
        }
    };
    if ca.is_none() && identity.is_none() {
        return Ok(None);
    }
    Ok(Some(ClientTls { ca, identity }))
}

fn tls_error(signal: &str, err: impl std::fmt::Display) -> TelemetryError {
    TelemetryError::new(format!("OTLP {signal} TLS: {err}"))
}

/// A reqwest client for the HTTP exporters carrying `tls` and `timeout`.
pub(super) fn http_client(
    signal: &str,
    tls: &ClientTls,
    timeout: Duration,
) -> Result<reqwest::Client, TelemetryError> {
    let mut builder = reqwest::Client::builder().timeout(timeout);
    if let Some(ca) = &tls.ca {
        let certificates =
            reqwest::Certificate::from_pem_bundle(ca).map_err(|err| tls_error(signal, err))?;
        if certificates.is_empty() {
            return Err(tls_error(signal, "the CA certificate file holds no certificate"));
        }
        builder = builder.tls_built_in_root_certs(false);
        for certificate in certificates {
            builder = builder.add_root_certificate(certificate);
        }
    }
    if let Some((cert, key)) = &tls.identity {
        let pem = [key.as_slice(), b"\n", cert.as_slice()].concat();
        let identity = reqwest::Identity::from_pem(&pem).map_err(|err| tls_error(signal, err))?;
        builder = builder.identity(identity);
    }
    builder.build().map_err(|err| tls_error(signal, err))
}

/// The tonic TLS settings for the gRPC exporters.
#[cfg(feature = "otel-grpc")]
pub(super) fn tonic_tls(
    tls: &ClientTls,
) -> opentelemetry_otlp::tonic_types::transport::ClientTlsConfig {
    use opentelemetry_otlp::tonic_types::transport::{Certificate, ClientTlsConfig, Identity};

    let mut config = ClientTlsConfig::new();
    if let Some(ca) = &tls.ca {
        config = config.ca_certificate(Certificate::from_pem(ca));
    }
    if let Some((cert, key)) = &tls.identity {
        config = config.identity(Identity::from_pem(cert, key));
    }
    config
}

#[cfg(test)]
#[path = "tls_tests.rs"]
mod tests;
