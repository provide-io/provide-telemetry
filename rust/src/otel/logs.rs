// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! LoggerProvider lifecycle + log emission for OTLP logs.
//!
//! Only compiled under the `otel` cargo feature. Mirrors the
//! traces.rs and metrics.rs designs: callers continue to go through
//! `logger::log_event()` (which gates on consent / sampling /
//! backpressure first); when a logger provider is present,
//! the same record that goes to stderr also gets pushed through the
//! global LoggerProvider for OTLP export.
//!
//! This is the dual-emission pattern the design plan calls L2:
//! stderr stays the local-dev path, OTLP is the production transport,
//! both fire when configured.

use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, SystemTime};

use opentelemetry::logs::{AnyValue, LogRecord, Logger, LoggerProvider as _, Severity};
#[cfg(feature = "otel-grpc")]
use opentelemetry_otlp::WithTonicConfig;
use opentelemetry_otlp::{LogExporter, Protocol, WithExportConfig, WithHttpConfig};
use opentelemetry_sdk::logs::log_processor_with_async_runtime::BatchLogProcessor;
use opentelemetry_sdk::logs::SdkLoggerProvider;
use opentelemetry_sdk::Resource;
use serde_json::Value;

use crate::config::TelemetryConfig;
use crate::errors::TelemetryError;
use crate::logger::LogEvent;

use super::async_runtime::ProvideTokioRuntime;
use super::endpoint::{resolve_protocol, validate_optional_endpoint, OtlpProtocol};
#[cfg(feature = "otel-grpc")]
use super::grpc::metadata_from_headers;
use super::map_exporter_build;
use super::resilient::ResilientLogExporter;

#[derive(Clone)]
struct InstalledLoggerProvider {
    provider: Arc<SdkLoggerProvider>,
    runtime: ProvideTokioRuntime,
}

static LOGGER_PROVIDER: OnceLock<Mutex<Option<InstalledLoggerProvider>>> = OnceLock::new();

const LOGGER_NAME: &str = "provide.telemetry";

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only swap in Mutex::default().
fn empty_logger_provider_mutex() -> Mutex<Option<InstalledLoggerProvider>> {
    Mutex::new(None)
}

fn logger_provider_slot() -> &'static Mutex<Option<InstalledLoggerProvider>> {
    LOGGER_PROVIDER.get_or_init(empty_logger_provider_mutex)
}

fn build_exporter(cfg: &TelemetryConfig) -> Result<LogExporter, TelemetryError> {
    let protocol = resolve_protocol(&cfg.logging.otlp_protocol)?;
    let timeout = Duration::from_secs_f64(cfg.exporter.logs_timeout_seconds);

    match protocol {
        OtlpProtocol::HttpProtobuf | OtlpProtocol::HttpJson => {
            let http_protocol = if protocol == OtlpProtocol::HttpJson {
                Protocol::HttpJson
            } else {
                Protocol::HttpBinary
            };
            let mut builder = LogExporter::builder()
                .with_http()
                .with_protocol(http_protocol)
                .with_timeout(timeout);
            let endpoint = validate_optional_endpoint(cfg.logging.otlp_endpoint.as_ref())?;
            if let Some(endpoint) = endpoint {
                builder = builder.with_endpoint(endpoint);
            }
            if !cfg.logging.otlp_headers.is_empty() {
                builder = builder.with_headers(cfg.logging.otlp_headers.clone());
            }
            map_exporter_build(builder.build(), "logs")
        }
        #[cfg(feature = "otel-grpc")]
        OtlpProtocol::Grpc => {
            let mut builder = LogExporter::builder().with_tonic().with_timeout(timeout);
            let endpoint = validate_optional_endpoint(cfg.logging.otlp_endpoint.as_ref())?;
            if let Some(endpoint) = endpoint {
                builder = builder.with_endpoint(endpoint);
            }
            if !cfg.logging.otlp_headers.is_empty() {
                builder = builder.with_metadata(metadata_from_headers(&cfg.logging.otlp_headers)?);
            }
            map_exporter_build(builder.build(), "logs")
        }
    }
}

/// Build and register the SDK `LoggerProvider`. Honours
/// `cfg.exporter.logs_fail_open`.
pub(super) fn install_logger_provider(
    cfg: &TelemetryConfig,
    resource: Resource,
) -> Result<bool, TelemetryError> {
    if cfg.logging.otlp_endpoint.is_none() {
        shutdown_logger_provider();
        return Ok(false);
    }

    let exporter_result = build_exporter(cfg);
    let exporter = match exporter_result {
        Ok(e) => e,
        Err(err) => {
            if cfg.exporter.logs_fail_open {
                eprintln!("provide_telemetry: logs exporter init failed (fail_open=true): {err}");
                return Ok(false);
            }
            return Err(err);
        }
    };

    let runtime = ProvideTokioRuntime::logs();
    let processor =
        BatchLogProcessor::builder(ResilientLogExporter::new(exporter), runtime.clone()).build();
    let provider = SdkLoggerProvider::builder()
        .with_resource(resource)
        .with_log_processor(processor)
        .build();

    let arc = Arc::new(provider);
    // OTel 0.31 doesn't expose a global logger-provider setter (unlike
    // tracer and meter), so we keep the provider only in our OnceLock
    // and emit_log() resolves through it directly.
    *logger_provider_slot()
        .lock()
        .expect("logger provider lock poisoned") = Some(InstalledLoggerProvider {
        provider: arc,
        runtime,
    });
    Ok(true)
}

/// Shut down the installed `LoggerProvider`.
pub(super) fn shutdown_logger_provider() {
    let mut guard = logger_provider_slot()
        .lock()
        .expect("logger provider lock poisoned");
    let provider = guard.take();
    drop(guard);
    if provider.is_none() {
        return;
    }
    let installed = provider.expect("logger provider must exist after none guard");
    installed.runtime.quiesce();
    let _ = installed.provider.force_flush();
    if let Err(err) = installed.provider.shutdown() {
        eprintln!("provide_telemetry: logs shutdown failed: {err:?}");
    }
    installed.runtime.quiesce();
}

pub(crate) fn logger_provider_installed() -> bool {
    logger_provider_slot()
        .lock()
        .expect("logger provider lock poisoned")
        .is_some()
}

/// Map our level string to OTel severity. Unknown levels default to
/// Info to match the safest behaviour at the receiving end.
fn level_to_severity(level: &str) -> (Severity, &'static str) {
    let normalized = level.to_ascii_uppercase();
    match normalized.as_str() {
        "TRACE" => (Severity::Trace, "TRACE"),
        "DEBUG" => (Severity::Debug, "DEBUG"),
        "INFO" => (Severity::Info, "INFO"),
        "WARN" => (Severity::Warn, "WARN"),
        "WARNING" => (Severity::Warn, "WARN"),
        "ERROR" => (Severity::Error, "ERROR"),
        "CRITICAL" => (Severity::Fatal, "FATAL"),
        "FATAL" => (Severity::Fatal, "FATAL"),
        _ => (Severity::Info, "INFO"),
    }
}

/// Convert our `serde_json::Value` context value to an OTel `AnyValue`.
/// Complex nested structures (object, array) flatten to JSON strings
/// to keep the attribute payload simple and collector-friendly.
fn json_to_any(v: &Value) -> AnyValue {
    match v {
        Value::Null => AnyValue::String("null".into()),
        Value::Bool(b) => AnyValue::Boolean(*b),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                AnyValue::Int(i)
            } else if let Some(u) = n.as_u64() {
                i64::try_from(u)
                    .map(AnyValue::Int)
                    .unwrap_or_else(|_| AnyValue::String(u.to_string().into()))
            } else {
                AnyValue::Double(
                    n.as_f64()
                        .expect("serde_json::Number must be representable as i64, u64, or f64"),
                )
            }
        }
        Value::String(s) => AnyValue::String(s.clone().into()),
        other => AnyValue::String(serde_json::to_string(other).unwrap_or_default().into()),
    }
}

fn parse_hex_u128(hex: &str) -> Option<u128> {
    if hex.len() == 32 {
        u128::from_str_radix(hex, 16).ok()
    } else {
        None
    }
}

fn parse_hex_u64(hex: &str) -> Option<u64> {
    if hex.len() == 16 {
        u64::from_str_radix(hex, 16).ok()
    } else {
        None
    }
}

/// Hot-path entry point: convert a LogEvent into an OTel LogRecord
/// and emit via the installed LoggerProvider. No-op when no provider
/// has been installed.
pub(crate) fn emit_log(event: &LogEvent) {
    let provider = logger_provider_slot()
        .lock()
        .expect("logger provider lock poisoned")
        .as_ref()
        .map(|installed| installed.provider.clone());
    let provider = match provider {
        Some(provider) => provider,
        None => return,
    };
    let logger = provider.logger(LOGGER_NAME);
    let mut record = logger.create_log_record();

    let (severity_number, severity_text) = level_to_severity(&event.level);
    record.set_severity_number(severity_number);
    record.set_severity_text(severity_text);
    record.set_body(AnyValue::String(event.message.clone().into()));
    record.set_observed_timestamp(SystemTime::now());

    record.add_attribute("logger.name", AnyValue::String(event.target.clone().into()));
    for (k, v) in &event.context {
        record.add_attribute(k.clone(), json_to_any(v));
    }

    // Correlate to the active span when our trace context carries
    // ids in the canonical 32/16-hex W3C format.
    if let (Some(tid), Some(sid)) = (&event.trace_id, &event.span_id) {
        if let (Some(t), Some(s)) = (parse_hex_u128(tid), parse_hex_u64(sid)) {
            record.set_trace_context(
                opentelemetry::trace::TraceId::from_bytes(t.to_be_bytes()),
                opentelemetry::trace::SpanId::from_bytes(s.to_be_bytes()),
                None,
            );
        }
    }

    logger.emit(record);
}

#[cfg(test)]
#[path = "logs_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "logs_export_test_support.rs"]
mod export_test_support;

#[cfg(test)]
#[path = "logs_export_tests.rs"]
mod export_tests;

#[cfg(test)]
#[path = "logs_export_runtime_tests.rs"]
mod export_runtime_tests;
