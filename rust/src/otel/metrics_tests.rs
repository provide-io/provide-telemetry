// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use super::*;
use std::sync::Arc;
use std::time::Duration;

use crate::testing::{acquire_test_state_lock, reset_telemetry_state};
use opentelemetry_sdk::error::{OTelSdkError, OTelSdkResult};
use opentelemetry_sdk::metrics::data::ResourceMetrics;
use opentelemetry_sdk::metrics::exporter::PushMetricExporter;
use opentelemetry_sdk::metrics::periodic_reader_with_async_runtime::PeriodicReader;
use opentelemetry_sdk::metrics::Temporality;

use crate::metrics::{counter, gauge, histogram};

fn test_config() -> TelemetryConfig {
    TelemetryConfig {
        service_name: "test".to_string(),
        ..TelemetryConfig::default()
    }
}

#[test]
fn metric_exporter_protocol_and_header_decisions_are_exact() {
    assert!(matches!(
        http_protocol_for(OtlpProtocol::HttpJson),
        Protocol::HttpJson
    ));
    assert!(matches!(
        http_protocol_for(OtlpProtocol::HttpProtobuf),
        Protocol::HttpBinary
    ));

    let mut cfg = test_config();
    assert!(!metric_headers_configured(&cfg));
    cfg.metrics
        .otlp_headers
        .insert("authorization".to_string(), "secret".to_string());
    assert!(metric_headers_configured(&cfg));
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
    shutdown_meter_provider(None);
    let cfg = test_config();
    let resource = super::super::resource::build_resource(&cfg);

    let installed = install_meter_provider(&cfg, resource).expect("missing endpoint is not error");

    assert!(!installed);
    assert!(!meter_provider_installed());
}

#[test]
fn shutdown_without_install_is_a_noop() {
    let _guard = acquire_test_state_lock();
    shutdown_meter_provider(None);
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

    let meta = |name| InstrumentMeta {
        name,
        description: None,
        unit: None,
    };
    record_counter_add(meta("test.counter"), 1.0, None);
    record_gauge_set(meta("test.gauge"), 42.0, None);
    record_histogram(meta("test.histogram"), 0.123, None);

    shutdown_meter_provider(None);
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
    shutdown_meter_provider(None);
    crate::_lock::lock(COUNTERS.get_or_init(empty_counter_cache_mutex)).clear();
    crate::_lock::lock(GAUGES.get_or_init(empty_gauge_cache_mutex)).clear();
    crate::_lock::lock(HISTOGRAMS.get_or_init(empty_histogram_cache_mutex)).clear();

    let _ = get_or_create_counter("reuse.counter", None, None);
    let _ = get_or_create_counter("reuse.counter", None, None);
    let _ = get_or_create_gauge("reuse.gauge", None, None);
    let _ = get_or_create_gauge("reuse.gauge", None, None);
    let _ = get_or_create_histogram("reuse.histogram", None, None);
    let _ = get_or_create_histogram("reuse.histogram", None, None);

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

    shutdown_meter_provider(None);
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

    shutdown_meter_provider(None);

    assert!(!meter_provider_installed());
}

#[test]
fn shutdown_meter_provider_logs_error_when_provider_is_already_shutdown() {
    let _guard = acquire_test_state_lock();
    shutdown_meter_provider(None);
    let provider = SdkMeterProvider::builder()
        .with_resource(super::super::resource::build_resource(&test_config()))
        .build();
    provider.shutdown().expect("first shutdown should succeed");
    *crate::_lock::lock(meter_provider_slot()) = Some(InstalledMeterProvider {
        provider: Arc::new(provider),
        runtime: ProvideTokioRuntime::test(),
    });

    shutdown_meter_provider(None);

    assert!(!meter_provider_installed());
}

/// (name, description, unit) of one exported metric.
type ExportedMeta = (String, String, String);

/// Records the identity metadata of every metric the SDK hands it, so a test
/// can assert on what an OTLP backend would actually receive.
#[derive(Debug, Default)]
struct CapturingMetricExporter {
    exported: Arc<Mutex<Vec<ExportedMeta>>>,
}

impl PushMetricExporter for CapturingMetricExporter {
    async fn export(&self, metrics: &ResourceMetrics) -> OTelSdkResult {
        let mut exported = crate::_lock::lock(&self.exported);
        for scope in metrics.scope_metrics() {
            for metric in scope.metrics() {
                exported.push((
                    metric.name().to_string(),
                    metric.description().to_string(),
                    metric.unit().to_string(),
                ));
            }
        }
        Ok(())
    }

    fn force_flush(&self) -> OTelSdkResult {
        Ok(())
    }

    fn shutdown_with_timeout(&self, _timeout: Duration) -> OTelSdkResult {
        Ok(())
    }

    fn temporality(&self) -> Temporality {
        Temporality::Cumulative
    }
}

/// Installs a provider whose only reader is a capturing exporter, both as the
/// global provider (which `get_or_create_*` builds instruments from) and in
/// the slot the facade checks before recording.
fn install_capturing_provider() -> (SdkMeterProvider, Arc<Mutex<Vec<ExportedMeta>>>) {
    let exporter = CapturingMetricExporter::default();
    let exported = Arc::clone(&exporter.exported);
    let reader = PeriodicReader::builder(exporter, ProvideTokioRuntime::test())
        .with_interval(Duration::from_secs(3600))
        .build();
    let provider = SdkMeterProvider::builder().with_reader(reader).build();
    global::set_meter_provider(provider.clone());
    install_meter_provider_for_tests(provider.clone());
    (provider, exported)
}

fn exported_named(exported: &Arc<Mutex<Vec<ExportedMeta>>>, name: &str) -> Vec<ExportedMeta> {
    crate::_lock::lock(exported)
        .iter()
        .filter(|(n, _, _)| n == name)
        .cloned()
        .collect()
}

fn meta(name: &str, description: &str, unit: &str) -> ExportedMeta {
    (name.to_string(), description.to_string(), unit.to_string())
}

#[test]
fn facade_unit_and_description_reach_the_exported_instruments() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    let (provider, exported) = install_capturing_provider();

    counter("units.counter", Some("requests served"), Some("{request}")).add(1.0, None);
    gauge("units.gauge", Some("pool utilisation"), Some("1")).set(0.5, None);
    gauge("units.gauge.add", Some("queue depth"), Some("{item}")).add(2.0, None);
    histogram("units.histogram", Some("request latency"), Some("ms")).record(12.0, None);
    provider.force_flush().expect("flush must export");

    assert_eq!(
        exported_named(&exported, "units.counter"),
        vec![meta("units.counter", "requests served", "{request}")]
    );
    assert_eq!(
        exported_named(&exported, "units.gauge"),
        vec![meta("units.gauge", "pool utilisation", "1")]
    );
    assert_eq!(
        exported_named(&exported, "units.gauge.add"),
        vec![meta("units.gauge.add", "queue depth", "{item}")]
    );
    assert_eq!(
        exported_named(&exported, "units.histogram"),
        vec![meta("units.histogram", "request latency", "ms")]
    );
    reset_telemetry_state();
}

#[test]
fn instruments_without_unit_or_description_export_them_empty() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    let (provider, exported) = install_capturing_provider();

    counter("bare.counter", None, None).add(1.0, None);
    gauge("bare.gauge", None, None).set(1.0, None);
    histogram("bare.histogram", None, None).record(1.0, None);
    provider.force_flush().expect("flush must export");

    for name in ["bare.counter", "bare.gauge", "bare.histogram"] {
        assert_eq!(exported_named(&exported, name), vec![meta(name, "", "")]);
    }
    reset_telemetry_state();
}

#[test]
fn first_recorded_unit_and_description_win_for_a_name() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    let (provider, exported) = install_capturing_provider();

    counter("dup.counter", Some("first"), Some("ms")).add(1.0, None);
    counter("dup.counter", Some("second"), Some("s")).add(1.0, None);
    gauge("dup.gauge", Some("first"), Some("ms")).set(1.0, None);
    gauge("dup.gauge", Some("second"), Some("s")).set(2.0, None);
    histogram("dup.histogram", Some("first"), Some("ms")).record(1.0, None);
    histogram("dup.histogram", None, None).record(2.0, None);
    provider.force_flush().expect("flush must export");

    for name in ["dup.counter", "dup.gauge", "dup.histogram"] {
        assert_eq!(
            exported_named(&exported, name),
            vec![meta(name, "first", "ms")],
            "a second registration must reuse the first instrument, not add a stream"
        );
    }
    reset_telemetry_state();
}
