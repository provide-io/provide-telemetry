// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// Cross-language distributed tracing E2E client.
//
// Uses provide-telemetry's setup_telemetry() for all signal setup, then creates
// a root span and injects W3C traceparent into an outgoing HTTP request.
//
// Required env vars:
//   E2E_BACKEND_URL — e.g. http://127.0.0.1:18765
//   OTEL_EXPORTER_OTLP_ENDPOINT
//   OTEL_EXPORTER_OTLP_HEADERS — Authorization=Basic <base64>

#[cfg(feature = "otel")]
use std::collections::HashMap;
#[cfg(feature = "otel")]
use std::env;
#[cfg(feature = "otel")]
use std::io::{Read, Write};
#[cfg(feature = "otel")]
use std::net::TcpStream;

#[cfg(feature = "otel")]
use opentelemetry::global;
#[cfg(feature = "otel")]
use opentelemetry::propagation::Injector;
#[cfg(feature = "otel")]
use opentelemetry::trace::{Span as _, TraceContextExt, Tracer as _};

#[cfg(feature = "otel")]
fn main() {
    if let Err(message) = run() {
        eprintln!("[rust-e2e-client] fatal: {message}");
        std::process::exit(1);
    }
}

#[cfg(not(feature = "otel"))]
fn main() {}

#[cfg(feature = "otel")]
fn run() -> Result<(), String> {
    let backend_url =
        env::var("E2E_BACKEND_URL").map_err(|_| "E2E_BACKEND_URL is required".to_string())?;

    // Use provide-telemetry's setup_telemetry() which installs the tracing subscriber,
    // registers the OTel TracerProvider globally, and sets the W3C propagator.
    provide_telemetry::setup_telemetry().map_err(|err| format!("setup_telemetry failed: {err}"))?;

    // Global tracer is now available — setup_telemetry() calls set_tracer_provider().
    let tracer = global::tracer("rust.e2e.client");

    let span = tracer.start("rust.e2e.cross_language_request");
    let trace_id = span.span_context().trace_id().to_string();
    let cx = opentelemetry::Context::current_with_span(span);

    // Inject W3C traceparent into request headers using the globally-installed propagator.
    let mut headers = HashMap::new();
    global::get_text_map_propagator(|propagator| {
        propagator.inject_context(&cx, &mut MapInjector::new(&mut headers));
    });

    send_get(&backend_url, "/traced", headers)?;

    cx.span().end();

    provide_telemetry::shutdown_telemetry()
        .map_err(|err| format!("shutdown_telemetry failed: {err}"))?;

    println!("TRACE_ID={trace_id}");
    Ok(())
}

// Minimal header injector for the OTel propagation API.
#[cfg(feature = "otel")]
struct MapInjector<'a> {
    headers: &'a mut HashMap<String, String>,
}

#[cfg(feature = "otel")]
impl<'a> MapInjector<'a> {
    fn new(headers: &'a mut HashMap<String, String>) -> Self {
        Self { headers }
    }
}

#[cfg(feature = "otel")]
impl Injector for MapInjector<'_> {
    fn set(&mut self, key: &str, value: String) {
        self.headers.insert(key.to_ascii_lowercase(), value);
    }
}

#[cfg(feature = "otel")]
fn send_get(backend_url: &str, path: &str, headers: HashMap<String, String>) -> Result<(), String> {
    let authority = backend_url
        .strip_prefix("http://")
        .ok_or_else(|| "only http:// backend URLs are supported".to_string())?;
    let mut stream = TcpStream::connect(authority)
        .map_err(|err| format!("failed to connect to backend: {err}"))?;
    let mut request = format!("GET {path} HTTP/1.1\r\nHost: {authority}\r\nConnection: close\r\n");
    for (key, value) in headers {
        request.push_str(&format!("{key}: {value}\r\n"));
    }
    request.push_str("\r\n");
    stream
        .write_all(request.as_bytes())
        .map_err(|err| format!("failed to write request: {err}"))?;

    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .map_err(|err| format!("failed to read response: {err}"))?;
    if !response.starts_with("HTTP/1.1 200") && !response.starts_with("HTTP/1.0 200") {
        let status = response.lines().next().unwrap_or("unknown response");
        return Err(format!("backend returned {status}"));
    }
    Ok(())
}
