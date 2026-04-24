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
#[cfg(feature = "otel-grpc")]
use opentelemetry_otlp::WithTonicConfig;
use opentelemetry_otlp::{MetricExporter, Protocol, WithExportConfig, WithHttpConfig};
use opentelemetry_sdk::metrics::periodic_reader_with_async_runtime::PeriodicReader;
use opentelemetry_sdk::metrics::SdkMeterProvider;
use opentelemetry_sdk::Resource;

use crate::config::TelemetryConfig;
use crate::errors::TelemetryError;

use super::async_runtime::ProvideTokioRuntime;
use super::endpoint::{resolve_protocol, validate_optional_endpoint, OtlpProtocol};
#[cfg(feature = "otel-grpc")]
use super::grpc::metadata_from_headers;
use super::map_exporter_build;
use super::resilient::ResilientMetricExporter;

#[derive(Clone)]
struct InstalledMeterProvider {
    provider: Arc<SdkMeterProvider>,
    runtime: ProvideTokioRuntime,
}

static METER_PROVIDER: OnceLock<Mutex<Option<InstalledMeterProvider>>> = OnceLock::new();
static COUNTERS: OnceLock<Mutex<HashMap<String, Counter<f64>>>> = OnceLock::new();
static GAUGES: OnceLock<Mutex<HashMap<String, Gauge<f64>>>> = OnceLock::new();
static HISTOGRAMS: OnceLock<Mutex<HashMap<String, Histogram<f64>>>> = OnceLock::new();

const METER_NAME: &str = "provide.telemetry";

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only swap in Mutex::default().
fn empty_meter_provider_mutex() -> Mutex<Option<InstalledMeterProvider>> {
    Mutex::new(None)
}

fn meter_provider_slot() -> &'static Mutex<Option<InstalledMeterProvider>> {
    METER_PROVIDER.get_or_init(empty_meter_provider_mutex)
}

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only swap in Mutex::default().
fn empty_counter_cache_mutex() -> Mutex<HashMap<String, Counter<f64>>> {
    Mutex::new(HashMap::new())
}

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only swap in Mutex::default().
fn empty_gauge_cache_mutex() -> Mutex<HashMap<String, Gauge<f64>>> {
    Mutex::new(HashMap::new())
}

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only swap in Mutex::default().
fn empty_histogram_cache_mutex() -> Mutex<HashMap<String, Histogram<f64>>> {
    Mutex::new(HashMap::new())
}

fn build_exporter(cfg: &TelemetryConfig) -> Result<MetricExporter, TelemetryError> {
    let protocol = resolve_protocol(&cfg.metrics.otlp_protocol)?;
    let timeout = Duration::from_secs_f64(cfg.exporter.metrics_timeout_seconds);

    match protocol {
        OtlpProtocol::HttpProtobuf | OtlpProtocol::HttpJson => {
            let http_protocol = if protocol == OtlpProtocol::HttpJson {
                Protocol::HttpJson
            } else {
                Protocol::HttpBinary
            };
            let mut builder = MetricExporter::builder()
                .with_http()
                .with_protocol(http_protocol)
                .with_timeout(timeout);
            let endpoint = validate_optional_endpoint(cfg.metrics.otlp_endpoint.as_ref())?;
            if let Some(endpoint) = endpoint {
                builder = builder.with_endpoint(endpoint);
            }
            if !cfg.metrics.otlp_headers.is_empty() {
                builder = builder.with_headers(cfg.metrics.otlp_headers.clone());
            }
            map_exporter_build(builder.build(), "metrics")
        }
        #[cfg(feature = "otel-grpc")]
        OtlpProtocol::Grpc => {
            let mut builder = MetricExporter::builder().with_tonic().with_timeout(timeout);
            let endpoint = validate_optional_endpoint(cfg.metrics.otlp_endpoint.as_ref())?;
            if let Some(endpoint) = endpoint {
                builder = builder.with_endpoint(endpoint);
            }
            if !cfg.metrics.otlp_headers.is_empty() {
                builder = builder.with_metadata(metadata_from_headers(&cfg.metrics.otlp_headers)?);
            }
            map_exporter_build(builder.build(), "metrics")
        }
    }
}

/// Build and register the SDK `MeterProvider`. Honours
/// `cfg.exporter.metrics_fail_open`.
pub(super) fn install_meter_provider(
    cfg: &TelemetryConfig,
    resource: Resource,
) -> Result<bool, TelemetryError> {
    if !cfg.metrics.enabled {
        shutdown_meter_provider();
        return Ok(false);
    }
    if cfg.metrics.otlp_endpoint.is_none() {
        shutdown_meter_provider();
        return Ok(false);
    }

    let exporter_result = build_exporter(cfg);
    let exporter = match exporter_result {
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

    let runtime = ProvideTokioRuntime::metrics();
    let reader = PeriodicReader::builder(ResilientMetricExporter::new(exporter), runtime)
        .with_interval(Duration::from_millis(cfg.metrics.metric_export_interval_ms))
        .build();

    let provider = SdkMeterProvider::builder()
        .with_resource(resource)
        .with_reader(reader)
        .build();

    let arc = Arc::new(provider);
    global::set_meter_provider(arc.as_ref().clone());
    *meter_provider_slot()
        .lock()
        .expect("meter provider lock poisoned") = Some(InstalledMeterProvider {
        provider: arc,
        runtime,
    });
    Ok(true)
}

/// Force-flush and shut down the installed `MeterProvider`.
pub(super) fn shutdown_meter_provider() {
    let mut guard = meter_provider_slot()
        .lock()
        .expect("meter provider lock poisoned");
    let provider = guard.take();
    drop(guard);
    if let Some(installed) = provider {
        installed.runtime.quiesce();
        let _ = installed.provider.force_flush();
        if let Err(err) = installed.provider.shutdown() {
            eprintln!("provide_telemetry: metrics shutdown failed: {err:?}");
        }
        installed.runtime.quiesce();
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
    match attrs {
        None => Vec::new(),
        Some(attrs) => attrs
            .iter()
            .map(|(key, value)| KeyValue::new(key.clone(), value.clone()))
            .collect(),
    }
}

/// Get-or-create an OTel Counter<f64> by name (cached).
fn get_or_create_counter(name: &str) -> Counter<f64> {
    let map = COUNTERS.get_or_init(empty_counter_cache_mutex);
    let mut guard = map.lock().expect("counter cache lock poisoned");
    if let Some(c) = guard.get(name).cloned() {
        return c.clone();
    }
    let meter = global::meter(METER_NAME);
    let counter = meter.f64_counter(name.to_string()).build();
    guard.insert(name.to_string(), counter.clone());
    counter
}

fn get_or_create_gauge(name: &str) -> Gauge<f64> {
    let map = GAUGES.get_or_init(empty_gauge_cache_mutex);
    let mut guard = map.lock().expect("gauge cache lock poisoned");
    if let Some(g) = guard.get(name).cloned() {
        return g.clone();
    }
    let meter = global::meter(METER_NAME);
    let gauge = meter.f64_gauge(name.to_string()).build();
    guard.insert(name.to_string(), gauge.clone());
    gauge
}

fn get_or_create_histogram(name: &str) -> Histogram<f64> {
    let map = HISTOGRAMS.get_or_init(empty_histogram_cache_mutex);
    let mut guard = map.lock().expect("histogram cache lock poisoned");
    if let Some(h) = guard.get(name).cloned() {
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
#[path = "metrics_tests.rs"]
mod tests;
