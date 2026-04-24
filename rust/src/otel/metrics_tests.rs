// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use super::*;
use std::sync::Arc;
use std::time::Duration;

use crate::testing::acquire_test_state_lock;
use opentelemetry_sdk::error::{OTelSdkError, OTelSdkResult};
use opentelemetry_sdk::metrics::data::ResourceMetrics;
use opentelemetry_sdk::metrics::exporter::PushMetricExporter;
use opentelemetry_sdk::metrics::periodic_reader_with_async_runtime::PeriodicReader;
use opentelemetry_sdk::metrics::Temporality;

fn test_config() -> TelemetryConfig {
    TelemetryConfig {
        service_name: "test".to_string(),
        ..TelemetryConfig::default()
    }
}

#[test]
fn install_with_disabled_metrics_is_a_noop() {
    let _guard = acquire_test_state_lock();
    let mut cfg = test_config();
    cfg.metrics.enabled = false;
    let resource = super::super::resource::build_resource(&cfg);
    install_meter_provider(&cfg, resource).expect("disabled metrics must short-circuit");
}

#[test]
fn install_without_endpoint_returns_false_and_leaves_provider_uninstalled() {
    let _guard = acquire_test_state_lock();
    shutdown_meter_provider();
    let cfg = test_config();
    let resource = super::super::resource::build_resource(&cfg);

    let installed = install_meter_provider(&cfg, resource).expect("missing endpoint is not error");

    assert!(!installed);
    assert!(!meter_provider_installed());
}

#[test]
fn shutdown_without_install_is_a_noop() {
    let _guard = acquire_test_state_lock();
    shutdown_meter_provider();
}

#[test]
fn build_exporter_rejects_invalid_endpoint_scheme() {
    let mut cfg = test_config();
    cfg.metrics.otlp_endpoint = Some("ftp://host:4318".to_string());
    let err = build_exporter(&cfg).expect_err("ftp scheme must be rejected");
    assert!(
        err.message.contains("scheme"),
        "error must mention bad scheme: {}",
        err.message
    );
}

#[test]
fn build_exporter_rejects_invalid_protocol() {
    let mut cfg = test_config();
    cfg.metrics.otlp_protocol = "kafka".to_string();

    let err = build_exporter(&cfg).expect_err("unknown OTLP protocol must fail");
    assert!(err.message.contains("protocol"));
}

#[test]
fn install_with_bad_endpoint_fails_closed_by_default() {
    let _guard = acquire_test_state_lock();
    let mut cfg = test_config();
    cfg.metrics.enabled = true;
    cfg.metrics.otlp_endpoint = Some("ftp://host:4318".to_string());
    cfg.exporter.metrics_fail_open = false;
    let resource = super::super::resource::build_resource(&cfg);
    let result = install_meter_provider(&cfg, resource);
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
    let _guard = acquire_test_state_lock();
    let mut cfg = test_config();
    cfg.metrics.enabled = true;
    cfg.metrics.otlp_endpoint = Some("ftp://host:4318".to_string());
    cfg.exporter.metrics_fail_open = true;
    let resource = super::super::resource::build_resource(&cfg);
    install_meter_provider(&cfg, resource).expect("fail_open must absorb validation error");
}

#[test]
fn install_with_unreachable_endpoint_succeeds_under_fail_open() {
    let _guard = acquire_test_state_lock();
    let mut cfg = test_config();
    cfg.metrics.otlp_endpoint = Some("http://127.0.0.1:1/never/v1/metrics".to_string());
    cfg.exporter.metrics_fail_open = true;
    let resource = super::super::resource::build_resource(&cfg);
    install_meter_provider(&cfg, resource).expect("install must succeed under fail_open");

    record_counter_add("test.counter", 1.0, None);
    record_gauge_set("test.gauge", 42.0, None);
    record_histogram("test.histogram", 0.123, None);

    shutdown_meter_provider();
}

#[test]
fn build_exporter_accepts_http_json_protocol() {
    let mut cfg = test_config();
    cfg.metrics.otlp_endpoint = Some("http://127.0.0.1:4318/v1/metrics".to_string());
    cfg.metrics.otlp_protocol = "http/json".to_string();
    cfg.metrics
        .otlp_headers
        .insert("authorization".to_string(), "Bearer token".to_string());

    build_exporter(&cfg).expect("http/json metrics exporter should build");
}

#[test]
fn build_exporter_accepts_http_defaults_without_endpoint_or_headers() {
    let mut cfg = test_config();
    cfg.metrics.otlp_protocol = "http/protobuf".to_string();
    cfg.metrics.otlp_endpoint = None;
    cfg.metrics.otlp_headers.clear();

    build_exporter(&cfg).expect("http defaults should build without explicit endpoint");
}

#[cfg(feature = "otel-grpc")]
#[tokio::test(flavor = "current_thread")]
async fn build_exporter_accepts_grpc_protocol_and_metadata() {
    let _guard = acquire_test_state_lock();
    let mut cfg = test_config();
    cfg.metrics.otlp_endpoint = Some("http://127.0.0.1:4317".to_string());
    cfg.metrics.otlp_protocol = "grpc".to_string();
    cfg.metrics
        .otlp_headers
        .insert("authorization".to_string(), "Bearer token".to_string());

    build_exporter(&cfg).expect("valid grpc endpoint and metadata should build");
}

#[cfg(feature = "otel-grpc")]
#[tokio::test(flavor = "current_thread")]
async fn build_exporter_accepts_grpc_defaults_without_endpoint_or_headers() {
    let _guard = acquire_test_state_lock();
    let mut cfg = test_config();
    cfg.metrics.otlp_protocol = "grpc".to_string();

    build_exporter(&cfg).expect("grpc defaults should build under a tokio runtime");
}

#[test]
fn attrs_to_kvs_handles_none_and_populated_attributes() {
    let mut attrs = BTreeMap::new();
    attrs.insert("service".to_string(), "metrics-test".to_string());

    assert!(attrs_to_kvs(None).is_empty());
    assert_eq!(attrs_to_kvs(Some(&attrs)).len(), 1);
}

#[test]
fn get_or_create_instruments_reuse_cached_instances() {
    let _guard = acquire_test_state_lock();
    shutdown_meter_provider();
    crate::_lock::lock(COUNTERS.get_or_init(empty_counter_cache_mutex)).clear();
    crate::_lock::lock(GAUGES.get_or_init(empty_gauge_cache_mutex)).clear();
    crate::_lock::lock(HISTOGRAMS.get_or_init(empty_histogram_cache_mutex)).clear();

    let _ = get_or_create_counter("reuse.counter");
    let _ = get_or_create_counter("reuse.counter");
    let _ = get_or_create_gauge("reuse.gauge");
    let _ = get_or_create_gauge("reuse.gauge");
    let _ = get_or_create_histogram("reuse.histogram");
    let _ = get_or_create_histogram("reuse.histogram");

    assert_eq!(
        crate::_lock::lock(COUNTERS.get().expect("counter cache must exist")).len(),
        1
    );
    assert_eq!(
        crate::_lock::lock(GAUGES.get().expect("gauge cache must exist")).len(),
        1
    );
    assert_eq!(
        crate::_lock::lock(HISTOGRAMS.get().expect("histogram cache must exist")).len(),
        1
    );
}

#[cfg(feature = "otel-grpc")]
#[test]
fn build_exporter_rejects_invalid_grpc_header_value() {
    let mut cfg = test_config();
    cfg.metrics.otlp_endpoint = Some("http://127.0.0.1:4317".to_string());
    cfg.metrics.otlp_protocol = "grpc".to_string();
    cfg.metrics
        .otlp_headers
        .insert("authorization".to_string(), "bad\nvalue".to_string());

    let err = build_exporter(&cfg).expect_err("invalid metadata must fail grpc exporter build");
    assert!(err.message.contains("build failed") || err.message.contains("invalid OTLP header"));
}

#[cfg(feature = "otel-grpc")]
#[test]
fn build_exporter_rejects_invalid_grpc_endpoint_scheme() {
    let mut cfg = test_config();
    cfg.metrics.otlp_endpoint = Some("ftp://127.0.0.1:4317".to_string());
    cfg.metrics.otlp_protocol = "grpc".to_string();

    let err = build_exporter(&cfg).expect_err("invalid grpc endpoint must fail");
    assert!(err.message.contains("scheme"));
}

#[derive(Debug)]
struct ShutdownErrorMetricExporter;

impl PushMetricExporter for ShutdownErrorMetricExporter {
    async fn export(&self, _metrics: &ResourceMetrics) -> OTelSdkResult {
        Ok(())
    }

    fn force_flush(&self) -> OTelSdkResult {
        Ok(())
    }

    fn shutdown_with_timeout(&self, _timeout: Duration) -> OTelSdkResult {
        Err(OTelSdkError::InternalFailure("test shutdown".into()))
    }

    fn temporality(&self) -> Temporality {
        Temporality::Cumulative
    }
}

#[test]
fn shutdown_meter_provider_clears_provider_even_when_reader_shutdown_errors() {
    let _guard = acquire_test_state_lock();
    let helper = ShutdownErrorMetricExporter;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime");
    runtime
        .block_on(helper.export(&ResourceMetrics::default()))
        .expect("helper export should succeed");
    helper
        .force_flush()
        .expect("helper force flush should succeed");
    assert_eq!(helper.temporality(), Temporality::Cumulative);

    shutdown_meter_provider();
    let reader = PeriodicReader::builder(ShutdownErrorMetricExporter, ProvideTokioRuntime::test())
        .with_interval(Duration::from_millis(10))
        .build();
    let provider = SdkMeterProvider::builder()
        .with_resource(super::super::resource::build_resource(&test_config()))
        .with_reader(reader)
        .build();
    *crate::_lock::lock(meter_provider_slot()) = Some(InstalledMeterProvider {
        provider: Arc::new(provider),
        runtime: ProvideTokioRuntime::test(),
    });

    shutdown_meter_provider();

    assert!(!meter_provider_installed());
}

#[test]
fn shutdown_meter_provider_logs_error_when_provider_is_already_shutdown() {
    let _guard = acquire_test_state_lock();
    shutdown_meter_provider();
    let provider = SdkMeterProvider::builder()
        .with_resource(super::super::resource::build_resource(&test_config()))
        .build();
    provider.shutdown().expect("first shutdown should succeed");
    *crate::_lock::lock(meter_provider_slot()) = Some(InstalledMeterProvider {
        provider: Arc::new(provider),
        runtime: ProvideTokioRuntime::test(),
    });

    shutdown_meter_provider();

    assert!(!meter_provider_installed());
}
