// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! TracerProvider lifecycle + span helpers.
//!
//! Only compiled under the `otel` cargo feature. Implements the
//! "OTel SDK behind our policy gates" architecture: callers continue
//! to go through `tracer::trace()` (which gates on consent / sampling /
//! backpressure first); when a tracer provider is present
//! `tracer::trace()` invokes [`start_span`] from this module instead
//! of producing a noop span.

use std::sync::{Arc, Mutex, OnceLock};
use std::time::Duration;

use opentelemetry::global;
use opentelemetry::trace::{Span, Tracer};
use opentelemetry_otlp::{Protocol, SpanExporter, WithExportConfig, WithHttpConfig};
use opentelemetry_sdk::trace::{Sampler, SdkTracerProvider};
use opentelemetry_sdk::Resource;

use crate::config::TelemetryConfig;
use crate::context::{set_trace_context_internal, ContextGuard};
use crate::errors::TelemetryError;

use super::endpoint::{resolve_protocol, validate_endpoint, OtlpProtocol};
use super::resilient::ResilientSpanExporter;

static TRACER_PROVIDER: OnceLock<Mutex<Option<Arc<SdkTracerProvider>>>> = OnceLock::new();

fn tracer_provider_slot() -> &'static Mutex<Option<Arc<SdkTracerProvider>>> {
    TRACER_PROVIDER.get_or_init(|| Mutex::new(None))
}

fn to_otlp_protocol(p: OtlpProtocol) -> Protocol {
    match p {
        OtlpProtocol::HttpProtobuf => Protocol::HttpBinary,
        OtlpProtocol::HttpJson => Protocol::HttpJson,
        #[cfg(feature = "otel-grpc")]
        OtlpProtocol::Grpc => Protocol::Grpc,
    }
}

/// Build the OTLP `SpanExporter` from `cfg.tracing` settings.
fn build_exporter(cfg: &TelemetryConfig) -> Result<SpanExporter, TelemetryError> {
    let protocol = resolve_protocol(&cfg.tracing.otlp_protocol)?;
    let otlp_protocol = to_otlp_protocol(protocol);
    let timeout = Duration::from_secs_f64(cfg.exporter.traces_timeout_seconds);

    let mut builder = SpanExporter::builder()
        .with_http()
        .with_protocol(otlp_protocol)
        .with_timeout(timeout);
    if let Some(endpoint) = &cfg.tracing.otlp_endpoint {
        validate_endpoint(endpoint)?;
        builder = builder.with_endpoint(endpoint.clone());
    }
    if !cfg.tracing.otlp_headers.is_empty() {
        builder = builder.with_headers(cfg.tracing.otlp_headers.clone());
    }
    builder
        .build()
        .map_err(|e| TelemetryError::new(format!("OTLP traces exporter build failed: {e}")))
}

/// Build and register the SDK `TracerProvider`. After this returns
/// `Ok`, [`start_span`] produces real OTel spans backed by the
/// installed batch processor.
///
/// Honours `cfg.exporter.traces_fail_open`: if exporter construction
/// fails and `fail_open` is true, logs to stderr and returns Ok so
/// telemetry emission silently degrades to noop instead of crashing
/// the host process.
pub(super) fn install_tracer_provider(
    cfg: &TelemetryConfig,
    resource: Resource,
) -> Result<bool, TelemetryError> {
    if !cfg.tracing.enabled {
        return Ok(false);
    }
    if cfg.tracing.otlp_endpoint.is_none() {
        return Ok(false);
    }

    let exporter = match build_exporter(cfg) {
        Ok(e) => e,
        Err(err) => {
            if cfg.exporter.traces_fail_open {
                eprintln!("provide_telemetry: traces exporter init failed (fail_open=true): {err}");
                return Ok(false);
            }
            return Err(err);
        }
    };

    let provider = SdkTracerProvider::builder()
        .with_resource(resource)
        .with_batch_exporter(ResilientSpanExporter::new(exporter))
        .with_sampler(Sampler::AlwaysOn)
        .build();

    let arc = Arc::new(provider);
    global::set_tracer_provider(arc.as_ref().clone());
    *tracer_provider_slot()
        .lock()
        .expect("tracer provider lock poisoned") = Some(arc);
    Ok(true)
}

/// Force-flush and shut down the installed `TracerProvider`. Safe to
/// call when no provider has been installed (no-op).
pub(super) fn shutdown_tracer_provider() {
    let mut guard = tracer_provider_slot()
        .lock()
        .expect("tracer provider lock poisoned");
    if let Some(p) = guard.take() {
        // shutdown() internally drains queued spans before returning, so
        // an explicit force_flush() beforehand is redundant — and in OTel
        // SDK 0.31 with rt-tokio, a force_flush followed by shutdown
        // surfaced "channel is empty and sending half is closed" because
        // shutdown was already initiated by the flush path. Just shutdown.
        if let Err(err) = p.shutdown() {
            eprintln!("provide_telemetry: traces shutdown failed: {err:?}");
        }
    }
}

pub(crate) fn tracer_provider_installed() -> bool {
    tracer_provider_slot()
        .lock()
        .expect("tracer provider lock poisoned")
        .is_some()
}

/// Wraps an OTel boxed span + the trace-context guard so that on drop
/// the span ends and the previous trace context is restored.
pub(crate) struct OtelSpanGuard {
    span: Option<global::BoxedSpan>,
    _context_guard: ContextGuard,
    // Exposed for tests / future callers; not read by the trace() entry
    // point itself, hence the allow(dead_code).
    #[allow(dead_code)]
    pub trace_id: String,
    #[allow(dead_code)]
    pub span_id: String,
}

impl Drop for OtelSpanGuard {
    fn drop(&mut self) {
        if let Some(mut span) = self.span.take() {
            span.end();
        }
    }
}

/// Start a span via the installed global `TracerProvider`. Populates
/// our trace-context contextvars so that downstream `log_event()`
/// calls correlate to the same trace_id / span_id.
pub(crate) fn start_span(name: &str) -> OtelSpanGuard {
    let tracer = global::tracer("provide.telemetry");
    let span = tracer.start(name.to_string());
    let span_context = span.span_context();
    let trace_id = format!("{}", span_context.trace_id());
    let span_id = format!("{}", span_context.span_id());
    let context_guard = set_trace_context_internal(Some(trace_id.clone()), Some(span_id.clone()));
    OtelSpanGuard {
        span: Some(span),
        _context_guard: context_guard,
        trace_id,
        span_id,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_config() -> TelemetryConfig {
        TelemetryConfig {
            service_name: "test".to_string(),
            ..TelemetryConfig::default()
        }
    }

    #[test]
    fn install_with_disabled_tracing_is_a_noop() {
        let mut cfg = test_config();
        cfg.tracing.enabled = false;
        let resource = super::super::resource::build_resource(&cfg);
        // No tokio runtime present — but with tracing disabled we never
        // touch the exporter, so this must succeed.
        install_tracer_provider(&cfg, resource).expect("disabled tracing must short-circuit");
    }

    #[test]
    fn shutdown_without_install_is_a_noop() {
        // Calling shutdown when nothing was ever installed must not
        // panic; the OnceLock is empty.
        shutdown_tracer_provider();
    }

    #[test]
    fn build_exporter_rejects_invalid_endpoint_scheme() {
        let mut cfg = test_config();
        cfg.tracing.otlp_endpoint = Some("ftp://host:4318".to_string());
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
        cfg.tracing.enabled = true;
        cfg.tracing.otlp_endpoint = Some("ftp://host:4318".to_string());
        cfg.exporter.traces_fail_open = false;
        let resource = super::super::resource::build_resource(&cfg);
        let result = install_tracer_provider(&cfg, resource);
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
        cfg.tracing.enabled = true;
        cfg.tracing.otlp_endpoint = Some("ftp://host:4318".to_string());
        cfg.exporter.traces_fail_open = true;
        let resource = super::super::resource::build_resource(&cfg);
        // fail_open means validation failure degrades gracefully
        install_tracer_provider(&cfg, resource).expect("fail_open must absorb validation error");
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 1)]
    async fn install_with_unreachable_endpoint_succeeds_and_start_span_emits_real_ids() {
        // Fail-open default: even with an endpoint that won't resolve,
        // setup must not error (the SDK retries asynchronously).
        let mut cfg = test_config();
        cfg.tracing.otlp_endpoint = Some("http://127.0.0.1:1/never".to_string());
        cfg.exporter.traces_fail_open = true;
        let resource = super::super::resource::build_resource(&cfg);
        install_tracer_provider(&cfg, resource).expect("install must succeed under fail_open");

        let guard = start_span("test.span");
        assert_eq!(guard.trace_id.len(), 32, "OTel trace_id is 16 bytes hex");
        assert_eq!(guard.span_id.len(), 16, "OTel span_id is 8 bytes hex");
        assert!(guard.trace_id.chars().all(|c| c.is_ascii_hexdigit()));
        // Drop guard ends the span; shutdown flushes the batch processor.
        drop(guard);
        shutdown_tracer_provider();
    }
}
