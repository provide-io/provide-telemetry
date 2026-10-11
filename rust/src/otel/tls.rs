// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Client TLS for the OTLP exporters: a private CA and mutual TLS from
//! `OTEL_EXPORTER_OTLP_{LOGS_,TRACES_,METRICS_,}{CERTIFICATE,CLIENT_CERTIFICATE,CLIENT_KEY}`,
//! the per-signal variable winning.
//!
//! See `prometheus_metrics.push_security` in `spec/telemetry-api.yaml`. Like the
//! other SDKs, the variables are read when an exporter is built, not by config
//! parsing. A configured file that cannot be read or loaded (a CA file with no
//! PEM certificate; a client certificate and key that do not form a pair)
//! leaves that signal's OTLP exporter unbuilt: [`ready`] logs
//! `otlp.tls_file_unreadable` and records the problem, which setup reports as
//! `setup_error`. Setup itself does not fail, and a configured CA replaces the
//! built-in roots rather than being ignored in favour of them.

use std::sync::{Mutex, OnceLock};
use std::time::Duration;

use crate::errors::TelemetryError;

/// What one signal's exporter trusts and presents: parsed for reqwest, raw PEM for tonic.
#[derive(Clone, Debug)]
pub(super) struct ClientTls {
    ca: Option<(Vec<u8>, Vec<reqwest::Certificate>)>,
    /// (certificate PEM, key PEM, parsed identity) for mutual TLS.
    identity: Option<(Vec<u8>, Vec<u8>, reqwest::Identity)>,
}

static PROBLEMS: OnceLock<Mutex<Vec<String>>> = OnceLock::new();

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only swap in Mutex::default().
fn empty_problems() -> Mutex<Vec<String>> {
    Mutex::new(Vec::new())
}

fn problems() -> &'static Mutex<Vec<String>> {
    PROBLEMS.get_or_init(empty_problems)
}

/// (path, variable name): the per-signal variable when set, else the shared one.
fn resolve(signal: &str, kind: &str) -> (Option<String>, String) {
    let own = format!("OTEL_EXPORTER_OTLP_{signal}_{kind}");
    let shared = format!("OTEL_EXPORTER_OTLP_{kind}");
    for name in [own, shared] {
        if let Some(path) = std::env::var(&name).ok().filter(|p| !p.trim().is_empty()) {
            return (Some(path.trim().to_string()), name);
        }
    }
    (None, format!("OTEL_EXPORTER_OTLP_{kind}"))
}

/// An I/O failure without the trailing "(os error N)".
fn io_reason(err: &std::io::Error) -> String {
    let text = err.to_string();
    match text.split_once(" (os error") {
        Some((reason, _)) => reason.to_string(),
        None => text,
    }
}

fn reqwest_failure(err: reqwest::Error) -> String {
    err.to_string()
}

/// Read and load `signal`'s TLS files (`signal` as in the variable names, e.g.
/// `METRICS`); `Ok(None)` when none is configured, `Err` naming the variable
/// and path of the first that cannot be read or loaded.
pub(super) fn client_tls(signal: &str) -> Result<Option<ClientTls>, String> {
    let (ca_path, ca_name) = resolve(signal, "CERTIFICATE");
    let (cert_path, cert_name) = resolve(signal, "CLIENT_CERTIFICATE");
    let (key_path, key_name) = resolve(signal, "CLIENT_KEY");
    let mut contents = Vec::new();
    for (name, path) in [
        (&ca_name, &ca_path),
        (&cert_name, &cert_path),
        (&key_name, &key_path),
    ] {
        contents.push(match path {
            Some(path) => Some(
                std::fs::read(path).map_err(|err| format!("{name}={path}: {}", io_reason(&err)))?,
            ),
            None => None,
        });
    }
    let (ca_pem, cert_pem, key_pem) = (contents[0].take(), contents[1].take(), contents[2].take());
    let ca = match (ca_pem, &ca_path) {
        (Some(pem), Some(path)) => {
            let certificates = reqwest::Certificate::from_pem_bundle(&pem).unwrap_or_default();
            if certificates.is_empty() {
                return Err(format!("{ca_name}={path}: no PEM certificates"));
            }
            Some((pem, certificates))
        }
        _ => None,
    };
    // A certificate without its key, or the reverse, configures no identity.
    let identity = match (cert_pem, key_pem, &cert_path, &key_path) {
        (Some(cert), Some(key), Some(cert_at), Some(key_at)) => {
            let parsed = load_pair(&cert, &key).map_err(|reason| {
                format!("{cert_name}={cert_at}, {key_name}={key_at}: {reason}")
            })?;
            Some((cert, key, parsed))
        }
        _ => None,
    };
    if ca.is_none() && identity.is_none() {
        return Ok(None);
    }
    Ok(Some(ClientTls { ca, identity }))
}

/// Parse a client certificate and key, and check that they form a pair.
fn load_pair(cert: &[u8], key: &[u8]) -> Result<reqwest::Identity, String> {
    let pem = [key, b"\n", cert].concat();
    let identity = reqwest::Identity::from_pem(&pem).map_err(reqwest_failure)?;
    // Building a client is what checks that the key belongs to the certificate.
    reqwest::Client::builder()
        .identity(identity.clone())
        .build()
        .map_err(reqwest_failure)?;
    Ok(identity)
}

/// Whether `signal`'s OTLP exporter may be built: its TLS files, if any, load.
/// When they do not, logs `otlp.tls_file_unreadable` and records the problem.
pub(super) fn ready(signal: &str) -> bool {
    let Err(problem) = client_tls(signal) else {
        return true;
    };
    eprintln!(
        "provide_telemetry: otlp.tls_file_unreadable signal={} error={problem}",
        signal.to_ascii_lowercase()
    );
    crate::_lock::lock(problems()).push(problem);
    false
}

/// The problems recorded since the last call, joined with "; ", or `None`; clears them.
pub(crate) fn take_problems() -> Option<String> {
    let mut recorded = crate::_lock::lock(problems());
    let joined = recorded.join("; ");
    recorded.clear();
    (!joined.is_empty()).then_some(joined)
}

/// A reqwest client for the HTTP exporters carrying `tls` and `timeout`.
pub(super) fn http_client(
    tls: &ClientTls,
    timeout: Duration,
) -> Result<reqwest::Client, TelemetryError> {
    let mut builder = reqwest::Client::builder().timeout(timeout);
    if let Some((_, certificates)) = &tls.ca {
        builder = builder.tls_built_in_root_certs(false);
        for certificate in certificates {
            builder = builder.add_root_certificate(certificate.clone());
        }
    }
    if let Some((_, _, identity)) = &tls.identity {
        builder = builder.identity(identity.clone());
    }
    builder
        .build()
        .map_err(reqwest_failure)
        .map_err(TelemetryError::new)
}

/// `signal`'s TLS for an exporter build; a file that stopped loading since
/// [`ready`] checked it is an ordinary build error.
pub(super) fn exporter_tls(signal: &str) -> Result<Option<ClientTls>, TelemetryError> {
    client_tls(signal).map_err(TelemetryError::new)
}

/// The tonic TLS settings for the gRPC exporters.
#[cfg(feature = "otel-grpc")]
pub(super) fn tonic_tls(
    tls: &ClientTls,
) -> opentelemetry_otlp::tonic_types::transport::ClientTlsConfig {
    use opentelemetry_otlp::tonic_types::transport::{Certificate, ClientTlsConfig, Identity};

    let mut config = ClientTlsConfig::new();
    if let Some((pem, _)) = &tls.ca {
        config = config.ca_certificate(Certificate::from_pem(pem));
    }
    if let Some((cert, key, _)) = &tls.identity {
        config = config.identity(Identity::from_pem(cert, key));
    }
    config
}

#[cfg(test)]
#[path = "tls_tests.rs"]
mod tests;
