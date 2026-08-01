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
#[cfg(feature = "otel-grpc")]
use opentelemetry_otlp::WithTonicConfig;
use opentelemetry_otlp::{Protocol, SpanExporter, WithExportConfig, WithHttpConfig};
use opentelemetry_sdk::trace::span_processor_with_async_runtime::BatchSpanProcessor;
use opentelemetry_sdk::trace::{Sampler, SdkTracerProvider};
use opentelemetry_sdk::Resource;

use crate::config::TelemetryConfig;
use crate::context::{set_trace_context_internal, ContextGuard};
use crate::errors::TelemetryError;

use super::async_runtime::ProvideTokioRuntime;
use super::endpoint::{resolve_protocol, validate_optional_endpoint, OtlpProtocol};
#[cfg(feature = "otel-grpc")]
use super::grpc::metadata_from_headers;
use super::map_exporter_build;
use super::resilient::ResilientSpanExporter;

#[derive(Clone)]
pub(super) struct InstalledTracerProvider {
    pub(super) provider: Arc<SdkTracerProvider>,
    runtime: ProvideTokioRuntime,
}

static TRACER_PROVIDER: OnceLock<Mutex<Option<InstalledTracerProvider>>> = OnceLock::new();

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only swap in Mutex::default().
fn empty_tracer_provider_mutex() -> Mutex<Option<InstalledTracerProvider>> {
    Mutex::new(None)
}

pub(super) fn tracer_provider_slot() -> &'static Mutex<Option<InstalledTracerProvider>> {
    TRACER_PROVIDER.get_or_init(empty_tracer_provider_mutex)
}

#[cfg(test)]
pub(super) fn install_tracer_provider_for_tests(provider: SdkTracerProvider) {
    *crate::_lock::lock(tracer_provider_slot()) = Some(InstalledTracerProvider {
        provider: Arc::new(provider),
        runtime: ProvideTokioRuntime::test(),
    });
}

/// Build the OTLP `SpanExporter` from `cfg.tracing` settings.
fn build_exporter(cfg: &TelemetryConfig) -> Result<SpanExporter, TelemetryError> {
    let protocol = resolve_protocol(&cfg.tracing.otlp_protocol)?;
    let timeout = Duration::from_secs_f64(cfg.exporter.traces_timeout_seconds);

    match protocol {
        OtlpProtocol::HttpProtobuf | OtlpProtocol::HttpJson => {
            let http_protocol = http_protocol_for(protocol);
            let mut builder = SpanExporter::builder()
                .with_http()
                .with_protocol(http_protocol)
                .with_timeout(timeout);
            let endpoint = validate_optional_endpoint(cfg.tracing.otlp_endpoint.as_ref())?;
            if let Some(endpoint) = endpoint {
                builder = builder.with_endpoint(endpoint);
            }
            if trace_headers_configured(cfg) {
                builder = builder.with_headers(cfg.tracing.otlp_headers.clone());
            }
            map_exporter_build(builder.build(), "traces")
        }
        #[cfg(feature = "otel-grpc")]
        OtlpProtocol::Grpc => {
            let mut builder = SpanExporter::builder().with_tonic().with_timeout(timeout);
            let endpoint = validate_optional_endpoint(cfg.tracing.otlp_endpoint.as_ref())?;
            if let Some(endpoint) = endpoint {
                builder = builder.with_endpoint(endpoint);
            }
            if trace_headers_configured(cfg) {
                builder = builder.with_metadata(metadata_from_headers(&cfg.tracing.otlp_headers)?);
            }
            map_exporter_build(builder.build(), "traces")
        }
    }
}

fn http_protocol_for(protocol: OtlpProtocol) -> Protocol {
    if protocol == OtlpProtocol::HttpJson {
        Protocol::HttpJson
    } else {
        Protocol::HttpBinary
    }
}

fn trace_headers_configured(cfg: &TelemetryConfig) -> bool {
    !cfg.tracing.otlp_headers.is_empty()
}

/// Build the ParentBased(TraceIdRatioBased) sampler for the effective rate.
pub(crate) fn sdk_trace_sampler(rate: f64) -> Sampler {
    let rate = rate.clamp(0.0, 1.0);
    let root = if rate <= 0.0 {
        Sampler::AlwaysOff
    } else if rate >= 1.0 {
        Sampler::AlwaysOn
    } else {
        Sampler::TraceIdRatioBased(rate)
    };
    Sampler::ParentBased(Box::new(root))
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
        shutdown_tracer_provider();
        return Ok(false);
    }
    if cfg.tracing.otlp_endpoint.is_none() {
        shutdown_tracer_provider();
        return Ok(false);
    }

    let exporter_result = build_exporter(cfg);
    let exporter = match exporter_result {
        Ok(e) => e,
        Err(err) => {
            if cfg.exporter.traces_fail_open {
                eprintln!("provide_telemetry: traces exporter init failed (fail_open=true): {err}");
                return Ok(false);
            }
            return Err(err);
        }
    };

    let runtime = ProvideTokioRuntime::traces();
    let processor =
        BatchSpanProcessor::builder(ResilientSpanExporter::new(exporter), runtime).build();
    // SDK sampler is the single sampling authority for live OTel spans.
    // Facade tracer::trace() skips ShouldSample when a provider is installed.
    let sampler = sdk_trace_sampler(cfg.sampling.traces_rate.min(cfg.tracing.sample_rate));
    let provider = SdkTracerProvider::builder()
        .with_resource(resource)
        .with_span_processor(processor)
        .with_sampler(sampler)
        .build();

    let arc = Arc::new(provider);
    global::set_tracer_provider(arc.as_ref().clone());
    *crate::_lock::lock(tracer_provider_slot()) = Some(InstalledTracerProvider {
        provider: arc,
        runtime,
    });
    Ok(true)
}

/// Shut down the installed `TracerProvider`. Safe to
/// call when no provider has been installed (no-op).
pub(super) fn shutdown_tracer_provider() {
    let mut guard = crate::_lock::lock(tracer_provider_slot());
    let provider = guard.take();
    drop(guard);
    if let Some(installed) = provider {
        installed.runtime.quiesce();
        let _ = installed.provider.force_flush();
        if let Err(err) = installed.provider.shutdown() {
            eprintln!("provide_telemetry: traces shutdown failed: {err:?}");
        }
        installed.runtime.quiesce();
    }
}

pub(crate) fn tracer_provider_installed() -> bool {
    crate::_lock::lock(tracer_provider_slot()).is_some()
}

/// Wraps an OTel boxed span + the trace-context guard so that on drop
/// the span ends and the previous trace context is restored.
pub(crate) struct OtelSpanGuard {
    // BoxedSpan ends itself on drop. Keep it before the context guard so the
    // SDK observes the active facade context through the complete span life.
    _span: global::BoxedSpan,
    _context_guard: ContextGuard,
    // Exposed for tests / future callers; not read by the trace() entry
    // point itself, hence the allow(dead_code).
    #[allow(dead_code)]
    pub trace_id: String,
    #[allow(dead_code)]
    pub span_id: String,
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
        _span: span,
        _context_guard: context_guard,
        trace_id,
        span_id,
    }
}

#[cfg(test)]
#[path = "traces_tests.rs"]
mod tests;
