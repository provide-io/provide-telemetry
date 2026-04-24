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
struct InstalledTracerProvider {
    provider: Arc<SdkTracerProvider>,
    runtime: ProvideTokioRuntime,
}

static TRACER_PROVIDER: OnceLock<Mutex<Option<InstalledTracerProvider>>> = OnceLock::new();

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only swap in Mutex::default().
fn empty_tracer_provider_mutex() -> Mutex<Option<InstalledTracerProvider>> {
    Mutex::new(None)
}

fn tracer_provider_slot() -> &'static Mutex<Option<InstalledTracerProvider>> {
    TRACER_PROVIDER.get_or_init(empty_tracer_provider_mutex)
}

/// Build the OTLP `SpanExporter` from `cfg.tracing` settings.
fn build_exporter(cfg: &TelemetryConfig) -> Result<SpanExporter, TelemetryError> {
    let protocol = resolve_protocol(&cfg.tracing.otlp_protocol)?;
    let timeout = Duration::from_secs_f64(cfg.exporter.traces_timeout_seconds);

    match protocol {
        OtlpProtocol::HttpProtobuf | OtlpProtocol::HttpJson => {
            let http_protocol = if protocol == OtlpProtocol::HttpJson {
                Protocol::HttpJson
            } else {
                Protocol::HttpBinary
            };
            let mut builder = SpanExporter::builder()
                .with_http()
                .with_protocol(http_protocol)
                .with_timeout(timeout);
            let endpoint = validate_optional_endpoint(cfg.tracing.otlp_endpoint.as_ref())?;
            if let Some(endpoint) = endpoint {
                builder = builder.with_endpoint(endpoint);
            }
            if !cfg.tracing.otlp_headers.is_empty() {
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
            if !cfg.tracing.otlp_headers.is_empty() {
                builder = builder.with_metadata(metadata_from_headers(&cfg.tracing.otlp_headers)?);
            }
            map_exporter_build(builder.build(), "traces")
        }
    }
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
    let provider = SdkTracerProvider::builder()
        .with_resource(resource)
        .with_span_processor(processor)
        .with_sampler(Sampler::AlwaysOn)
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
        if self.span.is_none() {
            return;
        }
        let mut span = self.span.take().expect("span must exist after none guard");
        span.end();
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
    use std::sync::Arc;

    use crate::testing::{acquire_test_state_lock, reset_telemetry_state};

    fn test_config() -> TelemetryConfig {
        TelemetryConfig {
            service_name: "test".to_string(),
            ..TelemetryConfig::default()
        }
    }

    fn reset_traces_test_state() -> std::sync::MutexGuard<'static, ()> {
        let guard = acquire_test_state_lock();
        reset_telemetry_state();
        shutdown_tracer_provider();
        guard
    }

    #[test]
    fn install_with_disabled_tracing_is_a_noop() {
        let _guard = reset_traces_test_state();
        let mut cfg = test_config();
        cfg.tracing.enabled = false;
        let resource = super::super::resource::build_resource(&cfg);
        // No tokio runtime present — but with tracing disabled we never
        // touch the exporter, so this must succeed.
        install_tracer_provider(&cfg, resource).expect("disabled tracing must short-circuit");
    }

    #[test]
    fn install_without_endpoint_returns_false_and_leaves_provider_uninstalled() {
        let _guard = reset_traces_test_state();
        let cfg = test_config();
        let resource = super::super::resource::build_resource(&cfg);

        let installed =
            install_tracer_provider(&cfg, resource).expect("missing endpoint is not error");

        assert!(!installed);
        assert!(!tracer_provider_installed());
    }

    #[test]
    fn shutdown_without_install_is_a_noop() {
        let _guard = reset_traces_test_state();
        // Calling shutdown when nothing was ever installed must not
        // panic; the OnceLock is empty.
        shutdown_tracer_provider();
    }

    #[test]
    fn build_exporter_rejects_invalid_endpoint_scheme() {
        let _guard = reset_traces_test_state();
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
    fn build_exporter_rejects_invalid_protocol() {
        let _guard = reset_traces_test_state();
        let mut cfg = test_config();
        cfg.tracing.otlp_protocol = "kafka".to_string();

        let err = build_exporter(&cfg).expect_err("unknown OTLP protocol must fail");
        assert!(err.message.contains("protocol"));
    }

    #[test]
    fn install_with_bad_endpoint_fails_closed_by_default() {
        let _guard = reset_traces_test_state();
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
        let _guard = reset_traces_test_state();
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
        let _guard = reset_traces_test_state();
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
        assert!(guard.span_id.chars().all(|c| c.is_ascii_hexdigit()));
        // Drop guard ends the span; shutdown flushes the batch processor.
        drop(guard);
        shutdown_tracer_provider();
    }

    #[test]
    fn build_exporter_accepts_http_json_protocol() {
        let _guard = reset_traces_test_state();
        let mut cfg = test_config();
        cfg.tracing.otlp_endpoint = Some("http://127.0.0.1:4318/v1/traces".to_string());
        cfg.tracing.otlp_protocol = "http/json".to_string();
        cfg.tracing
            .otlp_headers
            .insert("authorization".to_string(), "Bearer token".to_string());

        build_exporter(&cfg).expect("http/json traces exporter should build");
    }

    #[test]
    fn build_exporter_accepts_http_defaults_without_endpoint_or_headers() {
        let _guard = reset_traces_test_state();
        let mut cfg = test_config();
        cfg.tracing.otlp_protocol = "http/protobuf".to_string();
        cfg.tracing.otlp_endpoint = None;
        cfg.tracing.otlp_headers.clear();

        build_exporter(&cfg).expect("http defaults should build without explicit endpoint");
    }

    #[cfg(feature = "otel-grpc")]
    #[tokio::test(flavor = "current_thread")]
    async fn build_exporter_accepts_grpc_protocol_and_metadata() {
        let _guard = reset_traces_test_state();
        let mut cfg = test_config();
        cfg.tracing.otlp_endpoint = Some("http://127.0.0.1:4317".to_string());
        cfg.tracing.otlp_protocol = "grpc".to_string();
        cfg.tracing
            .otlp_headers
            .insert("authorization".to_string(), "Bearer token".to_string());

        build_exporter(&cfg).expect("valid grpc endpoint and metadata should build");
    }

    #[cfg(feature = "otel-grpc")]
    #[tokio::test(flavor = "current_thread")]
    async fn build_exporter_accepts_grpc_defaults_without_endpoint_or_headers() {
        let _guard = reset_traces_test_state();
        let mut cfg = test_config();
        cfg.tracing.otlp_protocol = "grpc".to_string();

        build_exporter(&cfg).expect("grpc defaults should build under a tokio runtime");
    }

    #[cfg(feature = "otel-grpc")]
    #[test]
    fn build_exporter_rejects_invalid_grpc_header_value() {
        let _guard = reset_traces_test_state();
        let mut cfg = test_config();
        cfg.tracing.otlp_endpoint = Some("http://127.0.0.1:4317".to_string());
        cfg.tracing.otlp_protocol = "grpc".to_string();
        cfg.tracing
            .otlp_headers
            .insert("authorization".to_string(), "bad\nvalue".to_string());

        let err = build_exporter(&cfg).expect_err("invalid metadata must fail grpc exporter build");
        assert!(
            err.message.contains("build failed") || err.message.contains("invalid OTLP header")
        );
    }

    #[cfg(feature = "otel-grpc")]
    #[test]
    fn build_exporter_rejects_invalid_grpc_endpoint_scheme() {
        let _guard = reset_traces_test_state();
        let mut cfg = test_config();
        cfg.tracing.otlp_endpoint = Some("ftp://127.0.0.1:4317".to_string());
        cfg.tracing.otlp_protocol = "grpc".to_string();

        let err = build_exporter(&cfg).expect_err("invalid grpc endpoint must fail");
        assert!(err.message.contains("scheme"));
    }

    #[test]
    fn dropping_otel_span_guard_ends_any_wrapped_span() {
        let _guard = reset_traces_test_state();
        let span = opentelemetry::global::tracer("tests.otel.traces").start("unit.span");
        let guard = OtelSpanGuard {
            span: Some(span),
            _context_guard: set_trace_context_internal(None, None),
            trace_id: "0".repeat(32),
            span_id: "0".repeat(16),
        };

        drop(guard);
    }

    #[test]
    fn dropping_otel_span_guard_without_span_is_a_noop() {
        let _guard = reset_traces_test_state();
        let guard = OtelSpanGuard {
            span: None,
            _context_guard: set_trace_context_internal(None, None),
            trace_id: String::new(),
            span_id: String::new(),
        };

        drop(guard);
    }

    #[test]
    fn shutdown_tracer_provider_clears_provider_even_when_processor_shutdown_errors() {
        let _guard = reset_traces_test_state();
        shutdown_tracer_provider();
        let provider = SdkTracerProvider::builder()
            .with_resource(super::super::resource::build_resource(&test_config()))
            .build();
        provider.shutdown().expect("first shutdown should succeed");
        *crate::_lock::lock(tracer_provider_slot()) = Some(InstalledTracerProvider {
            provider: Arc::new(provider),
            runtime: ProvideTokioRuntime::test(),
        });

        shutdown_tracer_provider();

        assert!(!tracer_provider_installed());
    }
}
