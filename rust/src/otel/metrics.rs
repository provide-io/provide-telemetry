// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! MeterProvider lifecycle + instrument helpers for OTLP metrics.
//!
//! Only compiled under the `otel` cargo feature. Mirrors the
//! traces.rs design: callers continue to go through
//! `metrics::counter()`/`gauge()`/`histogram()` (which gate on
//! consent / sampling / backpressure first); when a meter provider
//! provider is present, the instrument call also pushes a record
//! through the global MeterProvider.
//!
//! Mapping from our types to OTel instruments:
//! - `Counter::add`     → `opentelemetry::metrics::Counter<f64>::add`
//!   (monotonic)
//! - `Gauge::set`       → `opentelemetry::metrics::Gauge<f64>::record`
//!   (absolute value)
//! - `Histogram::record` → `opentelemetry::metrics::Histogram<f64>::record`
//!
//! `Gauge::add` is in-process only — we don't emit it to OTel because
//! mapping additive-with-history semantics cleanly to OTel
//! UpDownCounter would require a separate instrument with the same
//! name as the absolute Gauge, which collectors typically reject.

use std::collections::{BTreeMap, HashMap};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::Duration;

use opentelemetry::global;
use opentelemetry::metrics::{Counter, Gauge, Histogram};
use opentelemetry::KeyValue;
use opentelemetry_otlp::{MetricExporter, Protocol, WithExportConfig, WithHttpConfig};
use opentelemetry_sdk::metrics::{PeriodicReader, SdkMeterProvider};
use opentelemetry_sdk::Resource;

use crate::config::TelemetryConfig;
use crate::errors::TelemetryError;

use super::endpoint::{resolve_protocol, OtlpProtocol};

static METER_PROVIDER: OnceLock<Mutex<Option<Arc<SdkMeterProvider>>>> = OnceLock::new();
static COUNTERS: OnceLock<Mutex<HashMap<String, Counter<f64>>>> = OnceLock::new();
static GAUGES: OnceLock<Mutex<HashMap<String, Gauge<f64>>>> = OnceLock::new();
static HISTOGRAMS: OnceLock<Mutex<HashMap<String, Histogram<f64>>>> = OnceLock::new();

const METER_NAME: &str = "provide.telemetry";

fn meter_provider_slot() -> &'static Mutex<Option<Arc<SdkMeterProvider>>> {
    METER_PROVIDER.get_or_init(|| Mutex::new(None))
}

fn to_otlp_protocol(p: OtlpProtocol) -> Protocol {
    match p {
        OtlpProtocol::HttpProtobuf => Protocol::HttpBinary,
        OtlpProtocol::HttpJson => Protocol::HttpJson,
        #[cfg(feature = "otel-grpc")]
        OtlpProtocol::Grpc => Protocol::Grpc,
    }
}

fn build_exporter(cfg: &TelemetryConfig) -> Result<MetricExporter, TelemetryError> {
    let protocol = resolve_protocol(&cfg.metrics.otlp_protocol)?;
    let otlp_protocol = to_otlp_protocol(protocol);
    let timeout = Duration::from_secs_f64(cfg.exporter.metrics_timeout_seconds);

    let mut builder = MetricExporter::builder()
        .with_http()
        .with_protocol(otlp_protocol)
        .with_timeout(timeout);
    if let Some(endpoint) = &cfg.metrics.otlp_endpoint {
        builder = builder.with_endpoint(endpoint.clone());
    }
    if !cfg.metrics.otlp_headers.is_empty() {
        builder = builder.with_headers(cfg.metrics.otlp_headers.clone());
    }
    builder
        .build()
        .map_err(|e| TelemetryError::new(format!("OTLP metrics exporter build failed: {e}")))
}

/// Build and register the SDK `MeterProvider`. Honours
/// `cfg.exporter.metrics_fail_open`.
pub(super) fn install_meter_provider(
    cfg: &TelemetryConfig,
    resource: Resource,
) -> Result<bool, TelemetryError> {
    if !cfg.metrics.enabled {
        return Ok(false);
    }

    let exporter = match build_exporter(cfg) {
        Ok(e) => e,
        Err(err) => {
            if cfg.exporter.metrics_fail_open {
                eprintln!(
                    "provide_telemetry: metrics exporter init failed (fail_open=true): {err}"
                );
                return Ok(false);
            }
            return Err(err);
        }
    };

    let reader = PeriodicReader::builder(exporter)
        .with_interval(Duration::from_secs(60))
        .build();

    let provider = SdkMeterProvider::builder()
        .with_resource(resource)
        .with_reader(reader)
        .build();

    let arc = Arc::new(provider);
    global::set_meter_provider(arc.as_ref().clone());
    *meter_provider_slot()
        .lock()
        .expect("meter provider lock poisoned") = Some(arc);
    Ok(true)
}

/// Force-flush and shut down the installed `MeterProvider`.
pub(super) fn shutdown_meter_provider() {
    let mut guard = meter_provider_slot()
        .lock()
        .expect("meter provider lock poisoned");
    if let Some(p) = guard.take() {
        let _ = p.force_flush();
        let _ = p.shutdown();
    }
    // Drop cached instruments so a subsequent install gets fresh ones.
    if let Some(m) = COUNTERS.get() {
        m.lock().expect("counter cache lock poisoned").clear();
    }
    if let Some(m) = GAUGES.get() {
        m.lock().expect("gauge cache lock poisoned").clear();
    }
    if let Some(m) = HISTOGRAMS.get() {
        m.lock().expect("histogram cache lock poisoned").clear();
    }
}

pub(crate) fn meter_provider_installed() -> bool {
    meter_provider_slot()
        .lock()
        .expect("meter provider lock poisoned")
        .is_some()
}

fn attrs_to_kvs(attrs: Option<&BTreeMap<String, String>>) -> Vec<KeyValue> {
    attrs
        .map(|m| {
            m.iter()
                .map(|(k, v)| KeyValue::new(k.clone(), v.clone()))
                .collect()
        })
        .unwrap_or_default()
}

/// Get-or-create an OTel Counter<f64> by name (cached).
fn get_or_create_counter(name: &str) -> Counter<f64> {
    let map = COUNTERS.get_or_init(|| Mutex::new(HashMap::new()));
    let mut guard = map.lock().expect("counter cache lock poisoned");
    if let Some(c) = guard.get(name) {
        return c.clone();
    }
    let meter = global::meter(METER_NAME);
    let counter = meter.f64_counter(name.to_string()).build();
    guard.insert(name.to_string(), counter.clone());
    counter
}

fn get_or_create_gauge(name: &str) -> Gauge<f64> {
    let map = GAUGES.get_or_init(|| Mutex::new(HashMap::new()));
    let mut guard = map.lock().expect("gauge cache lock poisoned");
    if let Some(g) = guard.get(name) {
        return g.clone();
    }
    let meter = global::meter(METER_NAME);
    let gauge = meter.f64_gauge(name.to_string()).build();
    guard.insert(name.to_string(), gauge.clone());
    gauge
}

fn get_or_create_histogram(name: &str) -> Histogram<f64> {
    let map = HISTOGRAMS.get_or_init(|| Mutex::new(HashMap::new()));
    let mut guard = map.lock().expect("histogram cache lock poisoned");
    if let Some(h) = guard.get(name) {
        return h.clone();
    }
    let meter = global::meter(METER_NAME);
    let histogram = meter.f64_histogram(name.to_string()).build();
    guard.insert(name.to_string(), histogram.clone());
    histogram
}

/// Hot-path emission helpers. Called from metrics.rs after the
/// existing consent / sampling / backpressure gates have approved
/// the operation. No-op when no MeterProvider is installed (the
/// global default returns a noop meter that swallows the write).
pub(crate) fn record_counter_add(name: &str, value: f64, attrs: Option<&BTreeMap<String, String>>) {
    let kvs = attrs_to_kvs(attrs);
    get_or_create_counter(name).add(value, &kvs);
}

pub(crate) fn record_gauge_set(name: &str, value: f64, attrs: Option<&BTreeMap<String, String>>) {
    let kvs = attrs_to_kvs(attrs);
    get_or_create_gauge(name).record(value, &kvs);
}

pub(crate) fn record_histogram(name: &str, value: f64, attrs: Option<&BTreeMap<String, String>>) {
    let kvs = attrs_to_kvs(attrs);
    get_or_create_histogram(name).record(value, &kvs);
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
    fn install_with_disabled_metrics_is_a_noop() {
        let mut cfg = test_config();
        cfg.metrics.enabled = false;
        let resource = super::super::resource::build_resource(&cfg);
        install_meter_provider(&cfg, resource).expect("disabled metrics must short-circuit");
    }

    #[test]
    fn shutdown_without_install_is_a_noop() {
        shutdown_meter_provider();
    }

    #[test]
    fn install_with_unreachable_endpoint_succeeds_under_fail_open() {
        let mut cfg = test_config();
        cfg.metrics.otlp_endpoint = Some("http://127.0.0.1:1/never/v1/metrics".to_string());
        cfg.exporter.metrics_fail_open = true;
        let resource = super::super::resource::build_resource(&cfg);
        install_meter_provider(&cfg, resource).expect("install must succeed under fail_open");

        // Smoke-test the hot-path helpers — they must not panic when no
        // real provider is reachable.
        record_counter_add("test.counter", 1.0, None);
        record_gauge_set("test.gauge", 42.0, None);
        record_histogram("test.histogram", 0.123, None);

        shutdown_meter_provider();
    }
}
