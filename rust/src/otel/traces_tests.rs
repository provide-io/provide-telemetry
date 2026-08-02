// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use super::*;
use opentelemetry::Context;
use opentelemetry_sdk::error::OTelSdkResult;
use opentelemetry_sdk::trace::{Span as SdkSpan, SpanData, SpanProcessor};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use crate::testing::{acquire_test_state_lock, reset_telemetry_state};

fn test_config() -> TelemetryConfig {
    TelemetryConfig {
        service_name: "test".to_string(),
        ..TelemetryConfig::default()
    }
}

#[test]
fn trace_exporter_protocol_and_header_decisions_are_exact() {
    assert!(matches!(
        http_protocol_for(OtlpProtocol::HttpJson),
        Protocol::HttpJson
    ));
    assert!(matches!(
        http_protocol_for(OtlpProtocol::HttpProtobuf),
        Protocol::HttpBinary
    ));

    let mut cfg = test_config();
    assert!(!trace_headers_configured(&cfg));
    cfg.tracing
        .otlp_headers
        .insert("authorization".to_string(), "secret".to_string());
    assert!(trace_headers_configured(&cfg));
}

fn reset_traces_test_state() -> std::sync::MutexGuard<'static, ()> {
    let guard = acquire_test_state_lock();
    reset_telemetry_state();
    shutdown_tracer_provider(None);
    guard
}

#[derive(Debug)]
struct CountingEndProcessor {
    ended: Arc<AtomicUsize>,
}

impl SpanProcessor for CountingEndProcessor {
    fn on_start(&self, _span: &mut SdkSpan, _cx: &Context) {}

    fn on_end(&self, _span: SpanData) {
        self.ended.fetch_add(1, Ordering::SeqCst);
    }

    fn force_flush(&self) -> OTelSdkResult {
        Ok(())
    }

    fn shutdown_with_timeout(&self, _timeout: std::time::Duration) -> OTelSdkResult {
        Ok(())
    }
}

#[test]
fn sdk_trace_sampler_branches_cover_rate_bounds() {
    let off = format!("{:?}", sdk_trace_sampler(0.0));
    let on = format!("{:?}", sdk_trace_sampler(1.0));
    let mid = format!("{:?}", sdk_trace_sampler(0.25));
    let clamped_high = format!("{:?}", sdk_trace_sampler(2.0));
    let clamped_low = format!("{:?}", sdk_trace_sampler(-1.0));
    assert!(off.contains("AlwaysOff"));
    assert!(on.contains("AlwaysOn"));
    assert!(mid.contains("TraceIdRatioBased"));
    assert!(clamped_high.contains("AlwaysOn"));
    assert!(clamped_low.contains("AlwaysOff"));
    assert_ne!(off, mid);
    assert_ne!(on, mid);
    assert_eq!(on, clamped_high);
    assert_eq!(off, clamped_low);
}

#[test]
fn install_with_disabled_tracing_is_a_noop() {
    let _guard = reset_traces_test_state();
    let mut cfg = test_config();
    cfg.tracing.enabled = false;
    let resource = super::super::resource::build_resource(&cfg);
    install_tracer_provider(&cfg, resource).expect("disabled tracing must short-circuit");
}

#[test]
fn install_without_endpoint_returns_false_and_leaves_provider_uninstalled() {
    let _guard = reset_traces_test_state();
    let cfg = test_config();
    let resource = super::super::resource::build_resource(&cfg);
    let installed = install_tracer_provider(&cfg, resource).expect("missing endpoint is not error");
    assert!(!installed);
    assert!(!tracer_provider_installed());
}

#[test]
fn shutdown_without_install_is_a_noop() {
    let _guard = reset_traces_test_state();
    shutdown_tracer_provider(None);
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
    install_tracer_provider(&cfg, resource).expect("fail_open must absorb validation error");
}

#[tokio::test(flavor = "multi_thread", worker_threads = 1)]
async fn install_with_unreachable_endpoint_succeeds_and_start_span_emits_real_ids() {
    let _guard = reset_traces_test_state();
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
    drop(guard);
    shutdown_tracer_provider(None);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 1)]
async fn install_with_sample_rate_zero_still_installs_provider() {
    let _guard = reset_traces_test_state();
    let mut cfg = test_config();
    cfg.tracing.otlp_endpoint = Some("http://127.0.0.1:1/never".to_string());
    cfg.tracing.sample_rate = 0.0;
    cfg.sampling.traces_rate = 1.0;
    cfg.exporter.traces_fail_open = true;
    let resource = super::super::resource::build_resource(&cfg);
    let installed = install_tracer_provider(&cfg, resource).expect("rate-0 install must succeed");
    assert!(installed);
    assert!(tracer_provider_installed());
    let guard = start_span("dropped.span");
    assert_eq!(guard.trace_id.len(), 32);
    drop(guard);
    shutdown_tracer_provider(None);
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
    assert!(err.message.contains("build failed") || err.message.contains("invalid OTLP header"));
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
fn dropping_otel_span_guard_ends_the_sdk_span() {
    let _guard = reset_traces_test_state();
    let ended = Arc::new(AtomicUsize::new(0));
    let provider = SdkTracerProvider::builder()
        .with_span_processor(CountingEndProcessor {
            ended: Arc::clone(&ended),
        })
        .build();
    opentelemetry::global::set_tracer_provider(provider);

    let guard = start_span("unit.span");
    drop(guard);
    assert_eq!(ended.load(Ordering::SeqCst), 1);

    opentelemetry::global::set_tracer_provider(SdkTracerProvider::builder().build());
}

#[test]
fn shutdown_tracer_provider_clears_provider_even_when_processor_shutdown_errors() {
    let _guard = reset_traces_test_state();
    shutdown_tracer_provider(None);
    let provider = SdkTracerProvider::builder()
        .with_resource(super::super::resource::build_resource(&test_config()))
        .build();
    provider.shutdown().expect("first shutdown should succeed");
    *crate::_lock::lock(tracer_provider_slot()) = Some(InstalledTracerProvider {
        provider: Arc::new(provider),
        runtime: ProvideTokioRuntime::test(),
    });
    shutdown_tracer_provider(None);
    assert!(!tracer_provider_installed());
}
