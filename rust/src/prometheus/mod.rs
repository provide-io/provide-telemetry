// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Prometheus pull support: the endpoint status, the health families, and the
//! Tier 2 surface ([`render_prometheus`] and [`metrics_handler`]).
//!
//! See `prometheus_metrics` in `spec/telemetry-api.yaml`. Setup attaches a pull
//! reader to the meter provider it builds when `OTEL_METRICS_EXPORTER` includes
//! `prometheus` (or the listener is requested) and records here whether the
//! endpoint can serve. Each request then renders one collection, with the
//! health snapshot appended as `provide_telemetry_*` series. Nothing in this
//! module needs OpenTelemetry: the reader is handed in as a collector closure,
//! so without the `otel` feature the endpoint simply reports why it cannot serve.

use std::sync::{Arc, Mutex, OnceLock};

use crate::errors::TelemetryError;
use crate::health::{get_health_snapshot, HealthSnapshot};

pub(crate) mod names;
pub(crate) mod render;

#[cfg(feature = "prometheus-listener")]
pub(crate) mod listener;
#[cfg(feature = "prometheus-listener")]
mod web_config;

use render::{Family, PromType, RenderOptions, ResourceView};

/// Why the endpoint cannot serve, or that it can.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Status {
    NotSetUp,
    ShutDown,
    MetricsDisabled,
    #[cfg_attr(not(feature = "otel"), allow(dead_code))] // set when a provider is built
    HostProvider,
    NotSelected,
    #[cfg_attr(feature = "otel", allow(dead_code))] // only set without the otel feature
    OtelMissing,
    #[cfg_attr(not(feature = "otel"), allow(dead_code))] // set when a provider is built
    SetupFailed,
}

impl Status {
    /// The one-line reason a 503 carries.
    pub(crate) fn reason(self) -> &'static str {
        match self {
            Self::NotSetUp => "provide-telemetry: metrics are not set up yet",
            Self::ShutDown => "provide-telemetry: telemetry has been shut down",
            Self::MetricsDisabled => {
                "provide-telemetry: metrics are disabled (PROVIDE_METRICS_ENABLED=false)"
            }
            Self::HostProvider => {
                "provide-telemetry: the host application owns the MeterProvider; serve its registry instead"
            }
            Self::NotSelected => {
                "provide-telemetry: the Prometheus reader is not enabled (add prometheus to OTEL_METRICS_EXPORTER)"
            }
            Self::OtelMissing => {
                "provide-telemetry: the OpenTelemetry SDK is not compiled in (enable the otel feature)"
            }
            Self::SetupFailed => "provide-telemetry: the metrics provider failed to start",
        }
    }
}

/// Runs one collection on the attached reader.
pub(crate) type Collector = Arc<dyn Fn() -> ResourceView + Send + Sync>;

enum State {
    Waiting(Status),
    Ready(Collector, RenderOptions),
}

static STATE: OnceLock<Mutex<State>> = OnceLock::new();

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only change how the same initial state is built.
fn initial_state() -> Mutex<State> {
    Mutex::new(State::Waiting(Status::NotSetUp))
}

fn state() -> &'static Mutex<State> {
    STATE.get_or_init(initial_state)
}

/// Record a non-ready endpoint status, forgetting any reader.
pub(crate) fn set_status(status: Status) {
    *crate::_lock::lock(state()) = State::Waiting(status);
}

/// Record that `collector`, reading the installed provider, can serve.
#[cfg_attr(not(feature = "otel"), allow(dead_code))]
pub(crate) fn mark_ready(collector: Collector, options: RenderOptions) {
    *crate::_lock::lock(state()) = State::Ready(collector, options);
}

/// The render options a config selects (scrape-time negotiation adds UTF-8).
#[cfg_attr(not(feature = "otel"), allow(dead_code))]
pub(crate) fn options_for(config: &crate::config::TelemetryConfig) -> RenderOptions {
    let p = &config.metrics.prometheus;
    RenderOptions {
        strategy: p.translation.clone(),
        scope_labels: p.scope_labels,
        target_info: p.target_info,
    }
}

fn current() -> Result<(Collector, RenderOptions), Status> {
    match &*crate::_lock::lock(state()) {
        State::Waiting(status) => Err(*status),
        State::Ready(collector, options) => Ok((Arc::clone(collector), options.clone())),
    }
}

/// The health snapshot fields served per signal, in the spec's
/// `prometheus_metrics.health_metrics` order.
const PER_SIGNAL: [(&str, PromType); 8] = [
    ("provide_telemetry_emitted_total", PromType::Counter),
    ("provide_telemetry_dropped_total", PromType::Counter),
    ("provide_telemetry_export_failures_total", PromType::Counter),
    ("provide_telemetry_export_retries_total", PromType::Counter),
    (
        "provide_telemetry_export_latency_milliseconds",
        PromType::Gauge,
    ),
    (
        "provide_telemetry_async_blocking_risk_total",
        PromType::Counter,
    ),
    ("provide_telemetry_circuit_state", PromType::Gauge),
    ("provide_telemetry_circuit_open_total", PromType::Counter),
];

fn circuit_value(state: &str) -> f64 {
    match state {
        "closed" => 0.0,
        "half-open" => 1.0,
        "open" => 2.0,
        _ => -1.0,
    }
}

/// One signal's eight values, in [`PER_SIGNAL`] order.
fn signal_values(s: &HealthSnapshot, signal: crate::sampling::Signal) -> [f64; 8] {
    use crate::sampling::Signal;
    match signal {
        Signal::Logs => [
            s.emitted_logs as f64,
            s.dropped_logs as f64,
            s.export_failures_logs as f64,
            s.retries_logs as f64,
            s.export_latency_ms_logs,
            s.async_blocking_risk_logs as f64,
            circuit_value(&s.circuit_state_logs),
            s.circuit_open_count_logs as f64,
        ],
        Signal::Traces => [
            s.emitted_traces as f64,
            s.dropped_traces as f64,
            s.export_failures_traces as f64,
            s.retries_traces as f64,
            s.export_latency_ms_traces,
            s.async_blocking_risk_traces as f64,
            circuit_value(&s.circuit_state_traces),
            s.circuit_open_count_traces as f64,
        ],
        Signal::Metrics => [
            s.emitted_metrics as f64,
            s.dropped_metrics as f64,
            s.export_failures_metrics as f64,
            s.retries_metrics as f64,
            s.export_latency_ms_metrics,
            s.async_blocking_risk_metrics as f64,
            circuit_value(&s.circuit_state_metrics),
            s.circuit_open_count_metrics as f64,
        ],
    }
}

/// The health snapshot as `provide_telemetry_*` families.
pub(crate) fn health_families(snapshot: &HealthSnapshot) -> Vec<Family> {
    use crate::sampling::Signal;
    let signals = [
        ("logs", signal_values(snapshot, Signal::Logs)),
        ("traces", signal_values(snapshot, Signal::Traces)),
        ("metrics", signal_values(snapshot, Signal::Metrics)),
    ];
    let mut families: Vec<Family> = PER_SIGNAL
        .iter()
        .enumerate()
        .map(|(index, (metric, kind))| {
            let mut family = Family::new(metric, *kind, "");
            for (signal, values) in &signals {
                family.push(
                    vec![("signal".to_string(), (*signal).to_string())],
                    values[index],
                );
            }
            family
        })
        .collect();
    let has_error = snapshot
        .setup_error
        .as_deref()
        .is_some_and(|e| !e.is_empty());
    let mut setup_error = Family::new("provide_telemetry_setup_error", PromType::Gauge, "");
    setup_error.push(Vec::new(), if has_error { 1.0 } else { 0.0 });
    let mut receipts = Family::new(
        "provide_telemetry_receipt_failures_total",
        PromType::Counter,
        "",
    );
    receipts.push(Vec::new(), snapshot.receipt_failures as f64);
    families.push(setup_error);
    families.push(receipts);
    families
}

/// Run one collection and return `(body, content_type)` in the text format.
///
/// `accept` is the scraper's Accept header, if any; it decides whether UTF-8
/// names are allowed. Fails with the reason when there is nothing to serve:
/// before setup, after shutdown, with metrics disabled, when the host owns the
/// meter provider, or when the Prometheus reader was not selected.
pub fn render_prometheus(accept: Option<&str>) -> Result<(Vec<u8>, &'static str), TelemetryError> {
    let (collector, options) = current().map_err(|status| TelemetryError::new(status.reason()))?;
    let utf8 = render::wants_utf8(accept);
    let mut families = render::families_from(&collector(), &options, utf8);
    families.extend(health_families(&get_health_snapshot()));
    let content_type = if utf8 {
        render::CONTENT_TYPE_UTF8
    } else {
        render::CONTENT_TYPE_TEXT
    };
    Ok((render::render(&families).into_bytes(), content_type))
}

/// One HTTP response from [`metrics_handler`], for the host to write out.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MetricsResponse {
    pub status: u16,
    /// Lower-case header names and their values.
    pub headers: Vec<(&'static str, String)>,
    pub body: Vec<u8>,
}

const PLAIN_TEXT: &str = "text/plain; charset=utf-8";

/// The Tier 2 pull handler, framework-neutral: the host passes the request
/// method and Accept header from whatever HTTP server it runs and writes the
/// returned status, headers and body back.
///
/// It serves `GET` and `HEAD`, answers 405 otherwise, and 503 with a one-line
/// reason until setup has attached the Prometheus reader and after shutdown.
pub fn metrics_handler(method: &str, accept: Option<&str>) -> MetricsResponse {
    if method != "GET" && method != "HEAD" {
        return MetricsResponse {
            status: 405,
            headers: vec![
                ("allow", "GET, HEAD".to_string()),
                ("content-type", PLAIN_TEXT.to_string()),
            ],
            body: b"method not allowed\n".to_vec(),
        };
    }
    match render_prometheus(accept) {
        Err(err) => MetricsResponse {
            status: 503,
            headers: vec![("content-type", PLAIN_TEXT.to_string())],
            body: format!("{}\n", err.message).into_bytes(),
        },
        Ok((body, content_type)) => MetricsResponse {
            status: 200,
            headers: vec![("content-type", content_type.to_string())],
            body: if method == "GET" { body } else { Vec::new() },
        },
    }
}

/// Make the standalone listener match `config` after a successful setup.
pub(crate) fn sync_listener(config: &crate::config::TelemetryConfig) {
    #[cfg(feature = "prometheus-listener")]
    listener::sync(config);
    #[cfg(not(feature = "prometheus-listener"))]
    if config.metrics.prometheus_listener_enabled() {
        let message =
            "prometheus listener: rebuild provide-telemetry with the prometheus-listener feature";
        crate::health::set_setup_error(Some(message.to_string()));
        eprintln!("provide_telemetry: {message}");
    }
}

/// Stop the standalone listener, if one runs.
pub(crate) fn stop_listener() {
    #[cfg(feature = "prometheus-listener")]
    listener::stop();
}

#[cfg(test)]
#[path = "mod_tests.rs"]
mod tests;
