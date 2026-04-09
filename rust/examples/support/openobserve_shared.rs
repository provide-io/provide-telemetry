// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#![cfg(feature = "otel")]
#![allow(dead_code)]

use std::collections::HashMap;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use opentelemetry::logs::{AnyValue, LogRecord, Logger, LoggerProvider as _, Severity};
use opentelemetry::metrics::MeterProvider as _;
use opentelemetry::trace::{Tracer as _, TracerProvider as _};
use opentelemetry::KeyValue;
use opentelemetry_otlp::{
    LogExporter, MetricExporter, Protocol, SpanExporter, WithExportConfig, WithHttpConfig,
};
use opentelemetry_sdk::logs::SdkLoggerProvider;
use opentelemetry_sdk::metrics::SdkMeterProvider;
use opentelemetry_sdk::trace::SdkTracerProvider;
use opentelemetry_sdk::Resource;
use reqwest::blocking::Client;
use serde_json::{json, Value};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OpenObserveEndpoints {
    pub base_url: String,
    pub traces: String,
    pub metrics: String,
    pub logs: String,
    pub json_logs: String,
}

impl OpenObserveEndpoints {
    pub fn new(base_url: &str) -> Self {
        let base_url = base_url.trim_end_matches('/').to_string();
        Self {
            traces: format!("{base_url}/v1/traces"),
            metrics: format!("{base_url}/v1/metrics"),
            logs: format!("{base_url}/v1/logs"),
            json_logs: format!("{base_url}/default/_json"),
            base_url,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SignalNames {
    pub run_id: String,
    pub trace_name: String,
    pub metric_name: String,
    pub metric_stream: String,
    pub otlp_log_event: String,
    pub json_log_event: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EmitSummary {
    pub run_id: String,
    pub trace_name: String,
    pub metric_stream: String,
    pub otlp_log_event: String,
    pub json_log_event: String,
}

fn http_client() -> Result<Client, String> {
    Client::builder()
        .timeout(Duration::from_secs(10))
        .build()
        .map_err(|err| format!("failed to build HTTP client: {err}"))
}

fn otlp_headers(auth: &str) -> HashMap<String, String> {
    HashMap::from([("Authorization".to_string(), auth.to_string())])
}

fn resource(service_name: &str) -> Resource {
    Resource::builder_empty()
        .with_attributes([KeyValue::new("service.name", service_name.to_string())])
        .build()
}

pub fn require_env(name: &str) -> Result<String, String> {
    std::env::var(name).map_err(|_| format!("missing required env var: {name}"))
}

pub fn auth_header(user: &str, password: &str) -> String {
    use base64::Engine as _;

    let token = base64::engine::general_purpose::STANDARD.encode(format!("{user}:{password}"));
    format!("Basic {token}")
}

pub fn signal_names(run_id: Option<String>) -> SignalNames {
    let run_id = run_id.unwrap_or_else(|| {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis()
            .to_string()
    });
    let trace_name = format!("example.openobserve.work.{run_id}");
    let metric_name = format!("example.openobserve.requests.{run_id}");
    SignalNames {
        metric_stream: metric_name.replace('.', "_"),
        run_id,
        trace_name,
        metric_name,
        otlp_log_event: "example.openobserve.log".to_string(),
        json_log_event: "example.openobserve.jsonlog".to_string(),
    }
}

pub fn build_tracer_provider(
    endpoints: &OpenObserveEndpoints,
    auth: &str,
    service_name: &str,
) -> Result<SdkTracerProvider, String> {
    let exporter = SpanExporter::builder()
        .with_http()
        .with_protocol(Protocol::HttpBinary)
        .with_endpoint(endpoints.traces.clone())
        .with_http_client(http_client()?)
        .with_headers(otlp_headers(auth))
        .build()
        .map_err(|err| format!("failed to build trace exporter: {err}"))?;

    Ok(SdkTracerProvider::builder()
        .with_resource(resource(service_name))
        .with_simple_exporter(exporter)
        .build())
}

pub fn build_logger_provider(
    endpoints: &OpenObserveEndpoints,
    auth: &str,
    service_name: &str,
) -> Result<SdkLoggerProvider, String> {
    let exporter = LogExporter::builder()
        .with_http()
        .with_protocol(Protocol::HttpBinary)
        .with_endpoint(endpoints.logs.clone())
        .with_http_client(http_client()?)
        .with_headers(otlp_headers(auth))
        .build()
        .map_err(|err| format!("failed to build log exporter: {err}"))?;

    Ok(SdkLoggerProvider::builder()
        .with_resource(resource(service_name))
        .with_simple_exporter(exporter)
        .build())
}

pub fn build_meter_provider(
    endpoints: &OpenObserveEndpoints,
    auth: &str,
    service_name: &str,
) -> Result<SdkMeterProvider, String> {
    let exporter = MetricExporter::builder()
        .with_http()
        .with_protocol(Protocol::HttpBinary)
        .with_endpoint(endpoints.metrics.clone())
        .with_http_client(http_client()?)
        .with_headers(otlp_headers(auth))
        .build()
        .map_err(|err| format!("failed to build metric exporter: {err}"))?;

    Ok(SdkMeterProvider::builder()
        .with_resource(resource(service_name))
        .with_periodic_exporter(exporter)
        .build())
}

pub fn send_openobserve_json_log(
    endpoints: &OpenObserveEndpoints,
    auth: &str,
    names: &SignalNames,
) -> Result<(), String> {
    let payload = json!([{
        "_timestamp": SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_micros() as u64,
        "event": names.json_log_event,
        "run_id": names.run_id,
        "message": "openobserve json log ingestion",
    }]);

    let response = http_client()?
        .post(&endpoints.json_logs)
        .header("Authorization", auth)
        .json(&payload)
        .send()
        .map_err(|err| format!("failed to send OpenObserve JSON log: {err}"))?;
    if !response.status().is_success() {
        return Err(format!(
            "OpenObserve API returned status {}",
            response.status()
        ));
    }
    Ok(())
}

pub fn emit_all_signals(
    endpoints: &OpenObserveEndpoints,
    auth: &str,
    names: &SignalNames,
    service_name: &str,
) -> Result<EmitSummary, String> {
    let tracer_provider = build_tracer_provider(endpoints, auth, service_name)?;
    let logger_provider = build_logger_provider(endpoints, auth, service_name)?;
    let meter_provider = build_meter_provider(endpoints, auth, service_name)?;

    let tracer = tracer_provider.tracer("examples.openobserve");
    let logger = logger_provider.logger("examples.openobserve");
    let meter = meter_provider.meter("examples.openobserve");
    let requests = meter.u64_counter(names.metric_name.clone()).build();
    let latency = meter
        .f64_histogram(format!("example.openobserve.latency.{}", names.run_id))
        .build();

    let names_owned = names.clone();
    tracer.in_span(names.trace_name.clone(), |_cx| {
        for iteration in 0..5 {
            let mut record = logger.create_log_record();
            record.set_severity_number(Severity::Info);
            record.set_severity_text("INFO");
            record.set_body(AnyValue::from("openobserve otlp log"));
            record.add_attribute("event", names_owned.otlp_log_event.clone());
            record.add_attribute("run_id", names_owned.run_id.clone());
            record.add_attribute("iteration", iteration as i64);
            logger.emit(record);

            requests.add(
                1,
                &[
                    KeyValue::new("iteration", iteration as i64),
                    KeyValue::new("run_id", names_owned.run_id.clone()),
                ],
            );
            latency.record(
                50.0 + (iteration as f64),
                &[KeyValue::new("iteration", iteration as i64)],
            );
        }
    });

    tracer_provider
        .force_flush()
        .map_err(|err| format!("trace flush failed: {err}"))?;
    logger_provider
        .force_flush()
        .map_err(|err| format!("log flush failed: {err}"))?;
    meter_provider
        .force_flush()
        .map_err(|err| format!("metric flush failed: {err}"))?;

    tracer_provider
        .shutdown()
        .map_err(|err| format!("trace shutdown failed: {err}"))?;
    logger_provider
        .shutdown()
        .map_err(|err| format!("log shutdown failed: {err}"))?;
    meter_provider
        .shutdown()
        .map_err(|err| format!("metric shutdown failed: {err}"))?;

    send_openobserve_json_log(endpoints, auth, names)?;

    Ok(EmitSummary {
        run_id: names.run_id.clone(),
        trace_name: names.trace_name.clone(),
        metric_stream: names.metric_stream.clone(),
        otlp_log_event: names.otlp_log_event.clone(),
        json_log_event: names.json_log_event.clone(),
    })
}

pub fn request_json(
    url: &str,
    auth: &str,
    method: reqwest::Method,
    body: Option<Value>,
) -> Result<Value, String> {
    let client = http_client()?;
    let request = client.request(method, url).header("Authorization", auth);
    let request = if let Some(body) = body {
        request.json(&body)
    } else {
        request
    };
    let response = request
        .send()
        .map_err(|err| format!("request failed for {url}: {err}"))?;
    let status = response.status();
    let text = response
        .text()
        .map_err(|err| format!("failed to read response body: {err}"))?;
    if !status.is_success() {
        return Err(format!("OpenObserve API returned status {status}: {text}"));
    }
    serde_json::from_str(&text).map_err(|err| format!("invalid JSON response: {err}"))
}

pub fn search_hits(
    endpoints: &OpenObserveEndpoints,
    stream_type: &str,
    auth: &str,
    start_us: u64,
    end_us: u64,
) -> Result<Vec<Value>, String> {
    let body = json!({
        "query": {
            "sql": "select * from \"default\" order by _timestamp desc limit 500",
            "start_time": start_us,
            "end_time": end_us,
        }
    });
    let response = request_json(
        &format!("{}{}type={stream_type}", endpoints.base_url, "/_search?"),
        auth,
        reqwest::Method::POST,
        Some(body),
    )?;
    Ok(response
        .get("hits")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default())
}

pub fn metric_stream_names(
    endpoints: &OpenObserveEndpoints,
    auth: &str,
) -> Result<Vec<String>, String> {
    let response = request_json(
        &format!("{}{}type=metrics", endpoints.base_url, "/streams?"),
        auth,
        reqwest::Method::GET,
        None,
    )?;
    Ok(response
        .get("list")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|entry| {
            entry
                .get("name")
                .and_then(Value::as_str)
                .map(str::to_string)
        })
        .collect())
}
