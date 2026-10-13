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
use opentelemetry_otlp::{MetricExporter, Protocol, RetryPolicy, WithExportConfig, WithHttpConfig};
use opentelemetry_sdk::metrics::periodic_reader_with_async_runtime::PeriodicReader;
use opentelemetry_sdk::metrics::SdkMeterProvider;
use opentelemetry_sdk::Resource;

use crate::config::TelemetryConfig;
use crate::errors::TelemetryError;
use crate::prometheus::{self, Status};

use super::async_runtime::ProvideTokioRuntime;
use super::endpoint::{resolve_protocol, validate_optional_endpoint, OtlpProtocol};
#[cfg(feature = "otel-grpc")]
use super::grpc::metadata_from_headers;
use super::map_exporter_build;
use super::prometheus_reader::PullReader;
use super::resilient::ResilientMetricExporter;
#[cfg(feature = "otel-grpc")]
use super::tls::tonic_tls;
use super::tls::{exporter_tls, http_client};

#[derive(Clone)]
pub(super) struct InstalledMeterProvider {
    pub(super) provider: Arc<SdkMeterProvider>,
    runtime: ProvideTokioRuntime,
}

static METER_PROVIDER: OnceLock<Mutex<Option<InstalledMeterProvider>>> = OnceLock::new();
static COUNTERS: OnceLock<Mutex<HashMap<String, Counter<f64>>>> = OnceLock::new();
static GAUGES: OnceLock<Mutex<HashMap<String, Gauge<f64>>>> = OnceLock::new();
static HISTOGRAMS: OnceLock<Mutex<HashMap<String, Histogram<f64>>>> = OnceLock::new();

pub(super) const METER_NAME: &str = "provide.telemetry";

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only swap in Mutex::default().
fn empty_meter_provider_mutex() -> Mutex<Option<InstalledMeterProvider>> {
    Mutex::new(None)
}

pub(super) fn meter_provider_slot() -> &'static Mutex<Option<InstalledMeterProvider>> {
    METER_PROVIDER.get_or_init(empty_meter_provider_mutex)
}

#[cfg(test)]
pub(super) fn install_meter_provider_for_tests(provider: SdkMeterProvider) {
    *crate::_lock::lock(meter_provider_slot()) = Some(InstalledMeterProvider {
        provider: Arc::new(provider),
        runtime: ProvideTokioRuntime::test(),
    });
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
            let http_protocol = http_protocol_for(protocol);
            let mut builder = MetricExporter::builder()
                .with_http()
                .with_protocol(http_protocol)
                .with_timeout(timeout)
                // Retries belong to the SDK's resilience policy; the exporter's own would stack on them.
                .with_retry_policy(RetryPolicy::disabled());
            let endpoint = validate_optional_endpoint(cfg.metrics.otlp_endpoint.as_ref())?;
            if let Some(endpoint) = endpoint {
                builder = builder.with_endpoint(endpoint);
            }
            if metric_headers_configured(cfg) {
                builder = builder.with_headers(cfg.metrics.otlp_headers.clone());
            }
            if let Some(tls) = exporter_tls("METRICS")? {
                builder = builder.with_http_client(http_client(&tls, timeout)?);
            }
            map_exporter_build(builder.build(), "metrics")
        }
        #[cfg(feature = "otel-grpc")]
        OtlpProtocol::Grpc => {
            let mut builder = MetricExporter::builder()
                .with_tonic()
                .with_timeout(timeout)
                .with_retry_policy(RetryPolicy::disabled());
            let endpoint = validate_optional_endpoint(cfg.metrics.otlp_endpoint.as_ref())?;
            if let Some(endpoint) = endpoint {
                builder = builder.with_endpoint(endpoint);
            }
            if metric_headers_configured(cfg) {
                builder = builder.with_metadata(metadata_from_headers(&cfg.metrics.otlp_headers)?);
            }
            if let Some(tls) = exporter_tls("METRICS")? {
                builder = builder.with_tls_config(tonic_tls(&tls));
            }
            map_exporter_build(builder.build(), "metrics")
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

fn metric_headers_configured(cfg: &TelemetryConfig) -> bool {
    !cfg.metrics.otlp_headers.is_empty()
}

/// Build and register the SDK `MeterProvider` with the readers `cfg` selects:
/// the OTLP `PeriodicReader` (when `otlp` is selected and an endpoint is set)
/// and the Prometheus pull reader. Honours `cfg.exporter.metrics_fail_open`,
/// and records in [`crate::prometheus`] whether the pull endpoint can serve.
pub(super) fn install_meter_provider(
    cfg: &TelemetryConfig,
    resource: Resource,
) -> Result<bool, TelemetryError> {
    shutdown_meter_provider(None);
    let pull_status = pull_status(cfg);
    // TLS files that cannot be loaded skip only the OTLP reader; the pull
    // reader is unaffected, and setup reports the problem as setup_error.
    let want_otlp = cfg.metrics.otlp_reader_enabled()
        && cfg.metrics.otlp_endpoint.is_some()
        && super::tls::ready("METRICS");
    if !want_otlp && pull_status.is_some() {
        prometheus::set_status(pull_status.unwrap_or(Status::NotSelected));
        return Ok(false);
    }

    let runtime = ProvideTokioRuntime::metrics();
    let mut builder = SdkMeterProvider::builder().with_resource(resource);
    if want_otlp {
        let exporter = match build_exporter(cfg) {
            Ok(exporter) => exporter,
            Err(err) => {
                crate::health::set_setup_error(Some(err.message.clone()));
                prometheus::set_status(Status::SetupFailed);
                if cfg.exporter.metrics_fail_open {
                    eprintln!(
                        "provide_telemetry: metrics exporter init failed (fail_open=true): {err}"
                    );
                    return Ok(false);
                }
                return Err(err);
            }
        };
        let reader = PeriodicReader::builder(ResilientMetricExporter::new(exporter), runtime)
            .with_interval(Duration::from_millis(cfg.metrics.metric_export_interval_ms))
            .build();
        builder = builder.with_reader(reader);
    }
    let pull = pull_status.is_none().then(PullReader::new);
    if let Some(reader) = &pull {
        builder = builder.with_reader(reader.clone());
    }

    let arc = Arc::new(builder.build());
    if cfg.metrics.health_otlp {
        super::health_otlp::register(&arc);
    }
    global::set_meter_provider(arc.as_ref().clone());
    *crate::_lock::lock(meter_provider_slot()) = Some(InstalledMeterProvider {
        provider: arc,
        runtime,
    });
    match pull {
        Some(reader) => prometheus::mark_ready(
            Arc::new(move || reader.view()),
            prometheus::options_for(cfg),
        ),
        None => prometheus::set_status(pull_status.unwrap_or(Status::NotSelected)),
    }
    Ok(true)
}

/// Why the pull reader is not attached, or `None` when it is.
///
/// A host that adopted its own provider owns the global meter provider, so a
/// reader on ours would never see its instruments.
fn pull_status(cfg: &TelemetryConfig) -> Option<Status> {
    if !cfg.metrics.enabled {
        return Some(Status::MetricsDisabled);
    }
    if !cfg.metrics.prometheus_reader_enabled() {
        return Some(Status::NotSelected);
    }
    if super::adopt::metrics_adopted() {
        return Some(Status::HostProvider);
    }
    None
}

/// Force-flush and shut down the installed `MeterProvider`.
///
/// `timeout_seconds` is the caller's remaining budget; `None` uses the
/// configured one. Bounded for the same reason the tracer teardown is: the SDK
/// call has no timeout of its own.
///
/// The instrument caches are cleared on the calling thread, so a teardown
/// abandoned at the deadline still leaves a subsequent install with fresh ones.
pub(super) fn shutdown_meter_provider(timeout_seconds: Option<f64>) {
    let mut guard = crate::_lock::lock(meter_provider_slot());
    let provider = guard.take();
    drop(guard);
    if let Some(installed) = provider {
        super::bounded_teardown("metrics", timeout_seconds, move || {
            do_shutdown_meter_provider(installed);
        });
    }
    super::observable::clear_observed();
    // Drop cached instruments so a subsequent install gets fresh ones.
    if let Some(m) = COUNTERS.get() {
        crate::_lock::lock(m).clear();
    }
    if let Some(m) = GAUGES.get() {
        crate::_lock::lock(m).clear();
    }
    if let Some(m) = HISTOGRAMS.get() {
        crate::_lock::lock(m).clear();
    }
}

fn do_shutdown_meter_provider(installed: InstalledMeterProvider) {
    installed.runtime.quiesce();
    let _ = installed.provider.force_flush();
    if let Err(err) = installed.provider.shutdown() {
        eprintln!("provide_telemetry: metrics shutdown failed: {err:?}");
    }
    installed.runtime.quiesce();
}

pub(crate) fn meter_provider_installed() -> bool {
    crate::_lock::lock(meter_provider_slot()).is_some()
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
///
/// The cache is keyed by name alone, so the first call for a name since the
/// provider was installed fixes the instrument's unit and description. A later
/// call naming the same instrument with a different unit or description gets
/// the cached instrument and its original metadata; the new values are
/// ignored. OTel identifies an instrument by name, kind, unit and description,
/// so creating a second one would export two streams under one name, which
/// backends such as Prometheus reject or collide. The same rule applies to
/// gauges and histograms. A teardown clears the caches.
fn get_or_create_counter(
    name: &str,
    description: Option<&str>,
    unit: Option<&str>,
) -> Counter<f64> {
    let map = COUNTERS.get_or_init(empty_counter_cache_mutex);
    let mut guard = crate::_lock::lock(map);
    if let Some(c) = guard.get(name).cloned() {
        return c.clone();
    }
    let meter = global::meter(METER_NAME);
    let mut builder = meter.f64_counter(name.to_string());
    if let Some(description) = description {
        builder = builder.with_description(description.to_string());
    }
    if let Some(unit) = unit {
        builder = builder.with_unit(unit.to_string());
    }
    let counter = builder.build();
    guard.insert(name.to_string(), counter.clone());
    counter
}

fn get_or_create_gauge(name: &str, description: Option<&str>, unit: Option<&str>) -> Gauge<f64> {
    let map = GAUGES.get_or_init(empty_gauge_cache_mutex);
    let mut guard = crate::_lock::lock(map);
    if let Some(g) = guard.get(name).cloned() {
        return g.clone();
    }
    let meter = global::meter(METER_NAME);
    let mut builder = meter.f64_gauge(name.to_string());
    if let Some(description) = description {
        builder = builder.with_description(description.to_string());
    }
    if let Some(unit) = unit {
        builder = builder.with_unit(unit.to_string());
    }
    let gauge = builder.build();
    guard.insert(name.to_string(), gauge.clone());
    gauge
}

fn get_or_create_histogram(
    name: &str,
    description: Option<&str>,
    unit: Option<&str>,
) -> Histogram<f64> {
    let map = HISTOGRAMS.get_or_init(empty_histogram_cache_mutex);
    let mut guard = crate::_lock::lock(map);
    if let Some(h) = guard.get(name).cloned() {
        return h.clone();
    }
    let meter = global::meter(METER_NAME);
    let mut builder = meter.f64_histogram(name.to_string());
    if let Some(description) = description {
        builder = builder.with_description(description.to_string());
    }
    if let Some(unit) = unit {
        builder = builder.with_unit(unit.to_string());
    }
    let histogram = builder.build();
    guard.insert(name.to_string(), histogram.clone());
    histogram
}

/// Name, description and unit of a facade instrument, as passed to
/// `metrics::counter()`/`gauge()`/`histogram()`.
#[derive(Clone, Copy, Debug)]
pub(crate) struct InstrumentMeta<'a> {
    pub(crate) name: &'a str,
    pub(crate) description: Option<&'a str>,
    pub(crate) unit: Option<&'a str>,
}

/// Hot-path emission helpers. Called from metrics.rs after the
/// existing consent / sampling / backpressure gates have approved
/// the operation. No-op when no MeterProvider is installed (the
/// global default returns a noop meter that swallows the write).
pub(crate) fn record_counter_add(
    meta: InstrumentMeta<'_>,
    value: f64,
    attrs: Option<&BTreeMap<String, String>>,
) {
    let kvs = attrs_to_kvs(attrs);
    get_or_create_counter(meta.name, meta.description, meta.unit).add(value, &kvs);
}

pub(crate) fn record_gauge_set(
    meta: InstrumentMeta<'_>,
    value: f64,
    attrs: Option<&BTreeMap<String, String>>,
) {
    let kvs = attrs_to_kvs(attrs);
    get_or_create_gauge(meta.name, meta.description, meta.unit).record(value, &kvs);
}

pub(crate) fn record_histogram(
    meta: InstrumentMeta<'_>,
    value: f64,
    attrs: Option<&BTreeMap<String, String>>,
) {
    let kvs = attrs_to_kvs(attrs);
    get_or_create_histogram(meta.name, meta.description, meta.unit).record(value, &kvs);
}

#[cfg(test)]
#[path = "metrics_tests.rs"]
mod tests;
