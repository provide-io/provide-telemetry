// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

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
use opentelemetry::trace::{Span, SpanKind, Tracer as _, TracerProvider as _};

#[cfg(feature = "otel")]
#[path = "support/e2e_shared.rs"]
mod e2e_shared;

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

    let provider = e2e_shared::init_tracer_provider("rust-e2e-backend")?;
    let tracer = provider.tracer("rust.e2e.backend");
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
                provider
                    .force_flush()
                    .map_err(|err| format!("force flush failed: {err}"))?;
                provider
                    .shutdown()
                    .map_err(|err| format!("shutdown failed: {err}"))?;
                return Ok(());
            }
            "/traced" => {
                let parent = global::get_text_map_propagator(|propagator| {
                    propagator.extract(&e2e_shared::HeaderExtractor::new(&headers))
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
