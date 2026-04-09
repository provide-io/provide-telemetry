// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#![cfg(feature = "otel")]
#![allow(dead_code)]

use std::collections::HashMap;
use std::env;
use std::time::Duration;

use opentelemetry::global;
use opentelemetry::propagation::{Extractor, Injector};
use opentelemetry_otlp::{SpanExporter, WithExportConfig, WithHttpConfig};
use opentelemetry_sdk::propagation::TraceContextPropagator;
use opentelemetry_sdk::trace::SdkTracerProvider;

pub struct HeaderExtractor<'a> {
    headers: &'a HashMap<String, String>,
}

impl<'a> HeaderExtractor<'a> {
    pub fn new(headers: &'a HashMap<String, String>) -> Self {
        Self { headers }
    }
}

impl Extractor for HeaderExtractor<'_> {
    fn get(&self, key: &str) -> Option<&str> {
        self.headers
            .get(&key.to_ascii_lowercase())
            .map(std::string::String::as_str)
    }

    fn keys(&self) -> Vec<&str> {
        self.headers
            .keys()
            .map(std::string::String::as_str)
            .collect()
    }
}

pub struct HeaderInjector<'a> {
    headers: &'a mut HashMap<String, String>,
}

impl<'a> HeaderInjector<'a> {
    pub fn new(headers: &'a mut HashMap<String, String>) -> Self {
        Self { headers }
    }
}

impl Injector for HeaderInjector<'_> {
    fn set(&mut self, key: &str, value: String) {
        self.headers.insert(key.to_ascii_lowercase(), value);
    }
}

pub fn parse_headers_env(value: &str) -> HashMap<String, String> {
    let mut headers = HashMap::new();
    for pair in value.split(',') {
        let Some((key, header_value)) = pair.split_once('=') else {
            continue;
        };
        let key = key.trim();
        if key.is_empty() {
            continue;
        }
        headers.insert(key.to_string(), header_value.trim().to_string());
    }
    headers
}

pub fn traces_endpoint_from_env() -> Result<String, String> {
    if let Ok(value) = env::var("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") {
        return Ok(value);
    }
    if let Ok(value) = env::var("OTEL_EXPORTER_OTLP_ENDPOINT") {
        return Ok(format!("{}/v1/traces", value.trim_end_matches('/')));
    }
    Err("OTEL_EXPORTER_OTLP_ENDPOINT or OTEL_EXPORTER_OTLP_TRACES_ENDPOINT is required".to_string())
}

pub fn init_tracer_provider(_service_name: &str) -> Result<SdkTracerProvider, String> {
    let endpoint = traces_endpoint_from_env()?;
    let headers = env::var("OTEL_EXPORTER_OTLP_HEADERS")
        .map(|value| parse_headers_env(&value))
        .unwrap_or_default();

    global::set_text_map_propagator(TraceContextPropagator::new());

    let exporter = SpanExporter::builder()
        .with_http()
        .with_endpoint(endpoint)
        .with_http_client(
            reqwest::blocking::Client::builder()
                .timeout(Duration::from_secs(10))
                .build()
                .map_err(|err| format!("failed to build OTLP http client: {err}"))?,
        )
        .with_headers(headers)
        .build()
        .map_err(|err| format!("failed to build OTLP exporter: {err}"))?;

    let provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();

    Ok(provider)
}
