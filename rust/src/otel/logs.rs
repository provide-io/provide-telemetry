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
use opentelemetry_otlp::{LogExporter, Protocol, WithExportConfig, WithHttpConfig};
use opentelemetry_sdk::logs::SdkLoggerProvider;
use opentelemetry_sdk::Resource;
use serde_json::Value;

use crate::config::TelemetryConfig;
use crate::errors::TelemetryError;
use crate::logger::LogEvent;

use super::endpoint::{resolve_protocol, validate_endpoint, OtlpProtocol};
use super::resilient::ResilientLogExporter;

static LOGGER_PROVIDER: OnceLock<Mutex<Option<Arc<SdkLoggerProvider>>>> = OnceLock::new();

const LOGGER_NAME: &str = "provide.telemetry";

fn logger_provider_slot() -> &'static Mutex<Option<Arc<SdkLoggerProvider>>> {
    LOGGER_PROVIDER.get_or_init(|| Mutex::new(None))
}

fn to_otlp_protocol(p: OtlpProtocol) -> Protocol {
    match p {
        OtlpProtocol::HttpProtobuf => Protocol::HttpBinary,
        OtlpProtocol::HttpJson => Protocol::HttpJson,
        #[cfg(feature = "otel-grpc")]
        OtlpProtocol::Grpc => Protocol::Grpc,
    }
}

fn build_exporter(cfg: &TelemetryConfig) -> Result<LogExporter, TelemetryError> {
    let protocol = resolve_protocol(&cfg.logging.otlp_protocol)?;
    let otlp_protocol = to_otlp_protocol(protocol);
    let timeout = Duration::from_secs_f64(cfg.exporter.logs_timeout_seconds);

    let mut builder = LogExporter::builder()
        .with_http()
        .with_protocol(otlp_protocol)
        .with_timeout(timeout);
    if let Some(endpoint) = &cfg.logging.otlp_endpoint {
        validate_endpoint(endpoint)?;
        builder = builder.with_endpoint(endpoint.clone());
    }
    if !cfg.logging.otlp_headers.is_empty() {
        builder = builder.with_headers(cfg.logging.otlp_headers.clone());
    }
    builder
        .build()
        .map_err(|e| TelemetryError::new(format!("OTLP logs exporter build failed: {e}")))
}

/// Build and register the SDK `LoggerProvider`. Honours
/// `cfg.exporter.logs_fail_open`.
pub(super) fn install_logger_provider(
    cfg: &TelemetryConfig,
    resource: Resource,
) -> Result<bool, TelemetryError> {
    if cfg.logging.otlp_endpoint.is_none() {
        return Ok(false);
    }

    let exporter = match build_exporter(cfg) {
        Ok(e) => e,
        Err(err) => {
            if cfg.exporter.logs_fail_open {
                eprintln!("provide_telemetry: logs exporter init failed (fail_open=true): {err}");
                return Ok(false);
            }
            return Err(err);
        }
    };

    // BISECT: bypass ResilientLogExporter wrapper (same reactor-panic
    // diagnosis as traces.rs).
    let provider = SdkLoggerProvider::builder()
        .with_resource(resource)
        .with_batch_exporter(exporter)
        .build();

    let arc = Arc::new(provider);
    // OTel 0.31 doesn't expose a global logger-provider setter (unlike
    // tracer and meter), so we keep the provider only in our OnceLock
    // and emit_log() resolves through it directly.
    *logger_provider_slot()
        .lock()
        .expect("logger provider lock poisoned") = Some(arc);
    Ok(true)
}

/// Force-flush and shut down the installed `LoggerProvider`.
pub(super) fn shutdown_logger_provider() {
    let mut guard = logger_provider_slot()
        .lock()
        .expect("logger provider lock poisoned");
    if let Some(p) = guard.take() {
        // shutdown() drains internally; explicit force_flush before shutdown
        // confused the SDK channel state (see traces.rs comment).
        if let Err(err) = p.shutdown() {
            eprintln!("provide_telemetry: logs shutdown failed: {err:?}");
        }
    }
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
    match level {
        "TRACE" | "trace" => (Severity::Trace, "TRACE"),
        "DEBUG" | "debug" => (Severity::Debug, "DEBUG"),
        "INFO" | "info" => (Severity::Info, "INFO"),
        "WARN" | "WARNING" | "warn" | "warning" => (Severity::Warn, "WARN"),
        "ERROR" | "error" => (Severity::Error, "ERROR"),
        "CRITICAL" | "FATAL" | "critical" | "fatal" => (Severity::Fatal, "FATAL"),
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
            } else if let Some(f) = n.as_f64() {
                AnyValue::Double(f)
            } else {
                AnyValue::String(n.to_string().into())
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
        .clone();
    let Some(provider) = provider else {
        return;
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
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    fn test_config() -> TelemetryConfig {
        TelemetryConfig {
            service_name: "test".to_string(),
            ..TelemetryConfig::default()
        }
    }

    #[test]
    fn shutdown_without_install_is_a_noop() {
        shutdown_logger_provider();
    }

    #[test]
    fn build_exporter_rejects_invalid_endpoint_scheme() {
        let mut cfg = test_config();
        cfg.logging.otlp_endpoint = Some("ftp://host:4318".to_string());
        let err = build_exporter(&cfg).expect_err("ftp scheme must be rejected");
        assert!(
            err.message.contains("scheme"),
            "error must mention bad scheme: {}",
            err.message
        );
    }

    #[test]
    fn install_with_bad_endpoint_fails_closed_by_default() {
        let mut cfg = test_config();
        cfg.logging.otlp_endpoint = Some("ftp://host:4318".to_string());
        cfg.exporter.logs_fail_open = false;
        let resource = super::super::resource::build_resource(&cfg);
        let result = install_logger_provider(&cfg, resource);
        assert!(
            result.is_err(),
            "bad endpoint must return Err when fail_open=false"
        );
        let msg = result.unwrap_err().message;
        assert!(
            msg.contains("scheme"),
            "error must mention bad scheme: {msg}"
        );
    }

    #[test]
    fn install_with_bad_endpoint_succeeds_when_fail_open() {
        let mut cfg = test_config();
        cfg.logging.otlp_endpoint = Some("ftp://host:4318".to_string());
        cfg.exporter.logs_fail_open = true;
        let resource = super::super::resource::build_resource(&cfg);
        install_logger_provider(&cfg, resource).expect("fail_open must absorb validation error");
    }

    #[test]
    fn install_with_unreachable_endpoint_succeeds_under_fail_open() {
        let mut cfg = test_config();
        cfg.logging.otlp_endpoint = Some("http://127.0.0.1:1/never/v1/logs".to_string());
        cfg.exporter.logs_fail_open = true;
        let resource = super::super::resource::build_resource(&cfg);
        install_logger_provider(&cfg, resource).expect("install must succeed under fail_open");

        // emit_log must not panic even if delivery would fail.
        let event = LogEvent {
            level: "INFO".to_string(),
            target: "tests.otel.logs".to_string(),
            message: "test message".to_string(),
            context: BTreeMap::new(),
            trace_id: None,
            span_id: None,
            event_metadata: None,
        };
        emit_log(&event);
        shutdown_logger_provider();
    }

    #[test]
    fn level_to_severity_covers_all_defined_levels() {
        for (lvl, expect_text) in [
            ("TRACE", "TRACE"),
            ("DEBUG", "DEBUG"),
            ("INFO", "INFO"),
            ("WARN", "WARN"),
            ("WARNING", "WARN"),
            ("ERROR", "ERROR"),
            ("CRITICAL", "FATAL"),
            ("FATAL", "FATAL"),
            ("unknown", "INFO"),
        ] {
            let (_, text) = level_to_severity(lvl);
            assert_eq!(text, expect_text, "level {lvl} should map to {expect_text}");
        }
    }
}
