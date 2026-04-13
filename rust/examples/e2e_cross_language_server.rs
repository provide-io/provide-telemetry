// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// Cross-language distributed tracing E2E server.
//
// Uses provide-telemetry's setup_telemetry() for all signal setup, then creates
// child spans via the global OTel tracer API (which setup_telemetry installs).
// Accepts W3C traceparent from incoming requests and links child spans correctly.
//
// Required env vars:
//   PROVIDE_TELEMETRY_SERVICE_NAME — e.g. rust-e2e-backend
//   OTEL_EXPORTER_OTLP_TRACES_ENDPOINT or OTEL_EXPORTER_OTLP_ENDPOINT
//   OTEL_EXPORTER_OTLP_HEADERS — Authorization=Basic <base64>

#[cfg(feature = "otel")]
use std::collections::HashMap;
#[cfg(feature = "otel")]
use std::env;
#[cfg(feature = "otel")]
use std::io::{Read, Write};
#[cfg(feature = "otel")]
use std::net::TcpListener;

#[cfg(feature = "otel")]
use opentelemetry::global;
#[cfg(feature = "otel")]
use opentelemetry::propagation::Extractor;
#[cfg(feature = "otel")]
use opentelemetry::trace::{Span as _, SpanKind, Tracer as _};

#[cfg(feature = "otel")]
fn main() {
    if let Err(message) = run() {
        eprintln!("[rust-e2e-server] fatal: {message}");
        std::process::exit(1);
    }
}

#[cfg(not(feature = "otel"))]
fn main() {}

#[cfg(feature = "otel")]
fn run() -> Result<(), String> {
    let mut args = env::args().skip(1);
    let port = match (args.next().as_deref(), args.next()) {
        (Some("--port"), Some(value)) => value
            .parse::<u16>()
            .map_err(|err| format!("invalid --port value: {err}"))?,
        _ => 18765,
    };

    // Use provide-telemetry's setup_telemetry() which installs the tracing subscriber,
    // registers the OTel TracerProvider globally, and sets the W3C propagator.
    provide_telemetry::setup_telemetry()
        .map_err(|err| format!("setup_telemetry failed: {err}"))?;

    // Global tracer is now available — setup_telemetry() calls set_tracer_provider().
    let tracer = global::tracer("rust.e2e.backend");

    let listener = TcpListener::bind(("127.0.0.1", port))
        .map_err(|err| format!("failed to bind server: {err}"))?;

    println!("READY port={port}");
    for stream in listener.incoming() {
        let mut stream = stream.map_err(|err| format!("accept failed: {err}"))?;
        let (path, headers) = read_request(&mut stream)?;

        match path.as_str() {
            "/health" => respond(&mut stream, 200, b"ok")?,
            "/shutdown" => {
                respond(&mut stream, 200, b"ok")?;
                provide_telemetry::shutdown_telemetry()
                    .map_err(|err| format!("shutdown failed: {err}"))?;
                return Ok(());
            }
            "/traced" => {
                // Extract W3C traceparent from incoming headers.
                // setup_telemetry() installed the W3C TraceContextPropagator globally.
                let parent = global::get_text_map_propagator(|propagator| {
                    propagator.extract(&MapExtractor::new(&headers))
                });
                let mut span = tracer
                    .span_builder("rust.e2e.cross_language_handler")
                    .with_kind(SpanKind::Server)
                    .start_with_context(&tracer, &parent);
                span.end();
                respond(&mut stream, 200, b"ok")?;
            }
            _ => respond(&mut stream, 404, b"not found")?,
        }
    }

    Ok(())
}

// Minimal header extractor for the OTel propagation API.
#[cfg(feature = "otel")]
struct MapExtractor<'a> {
    headers: &'a HashMap<String, String>,
}

#[cfg(feature = "otel")]
impl<'a> MapExtractor<'a> {
    fn new(headers: &'a HashMap<String, String>) -> Self {
        Self { headers }
    }
}

#[cfg(feature = "otel")]
impl Extractor for MapExtractor<'_> {
    fn get(&self, key: &str) -> Option<&str> {
        self.headers
            .get(&key.to_ascii_lowercase())
            .map(String::as_str)
    }

    fn keys(&self) -> Vec<&str> {
        self.headers.keys().map(String::as_str).collect()
    }
}

#[cfg(feature = "otel")]
fn read_request(
    stream: &mut std::net::TcpStream,
) -> Result<(String, HashMap<String, String>), String> {
    let mut buffer = [0_u8; 8192];
    let bytes_read = stream
        .read(&mut buffer)
        .map_err(|err| format!("failed to read request: {err}"))?;
    let request = String::from_utf8_lossy(&buffer[..bytes_read]);
    let mut lines = request.split("\r\n");
    let request_line = lines
        .next()
        .ok_or_else(|| "missing request line".to_string())?;
    let mut parts = request_line.split_whitespace();
    let _method = parts.next().unwrap_or("GET");
    let path = parts.next().unwrap_or("/").to_string();
    let mut headers = HashMap::new();
    for line in lines {
        if line.is_empty() {
            break;
        }
        if let Some((key, value)) = line.split_once(':') {
            headers.insert(key.trim().to_ascii_lowercase(), value.trim().to_string());
        }
    }
    Ok((path, headers))
}

#[cfg(feature = "otel")]
fn respond(stream: &mut std::net::TcpStream, status: u16, body: &[u8]) -> Result<(), String> {
    let status_text = match status {
        200 => "OK",
        404 => "Not Found",
        _ => "Error",
    };
    let response = format!(
        "HTTP/1.1 {status} {status_text}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    stream
        .write_all(response.as_bytes())
        .and_then(|_| stream.write_all(body))
        .map_err(|err| format!("failed to write response: {err}"))
}
