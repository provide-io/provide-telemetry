// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// Demonstrates emitting all three signal types (logs, traces, metrics) through
// the provide-telemetry library's public API using setup_telemetry().
//
// Required env vars:
//   OTEL_EXPORTER_OTLP_ENDPOINT  — e.g. http://localhost:5080/api/default
//   OTEL_EXPORTER_OTLP_HEADERS   — e.g. Authorization=Basic <base64>
//   PROVIDE_TELEMETRY_SERVICE_NAME — e.g. provide-telemetry-rust-examples
//
// Optional:
//   PROVIDE_EXAMPLE_RUN_ID — tag to stamp on each signal for verification

#[cfg(feature = "otel")]
fn main() {
    use opentelemetry::trace::Tracer as _;
    use provide_telemetry::{counter, histogram, setup_telemetry, shutdown_telemetry};
    use std::collections::BTreeMap;
    use std::time::{SystemTime, UNIX_EPOCH};

    let run_id = std::env::var("PROVIDE_EXAMPLE_RUN_ID").unwrap_or_else(|_| {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis()
            .to_string()
    });

    setup_telemetry().expect("telemetry setup failed");

    // Traces: use the global OTel tracer that setup_telemetry() installs.
    // opentelemetry::global::tracer() uses the active TracerProvider, so this
    // is fully going through the library — setup_telemetry() wired it.
    let tracer = opentelemetry::global::tracer("example.openobserve");
    let span_name = format!("example.openobserve.work.{run_id}");
    let mut _span = tracer.start(span_name.clone());

    let requests = counter("example.openobserve.requests", None, None);
    let latency = histogram("example.openobserve.latency", None, Some("ms"));

    for i in 0..5i64 {
        // Logs: tracing events are bridged to OTLP by OpenTelemetryTracingBridge.
        // Structured fields become OTel log attributes in OpenObserve.
        // Logs: tracing events are bridged to OTLP by OpenTelemetryTracingBridge.
        // Structured fields become OTel log attributes in OpenObserve.
        tracing::info!(
            run_id = %run_id,
            event = "example.openobserve.log",
            iteration = i,
            "openobserve otlp log",
        );

        let mut attrs = BTreeMap::new();
        attrs.insert("run_id".to_string(), run_id.clone());
        attrs.insert("iteration".to_string(), i.to_string());
        requests.add(1.0, Some(attrs.clone()));
        latency.record(50.0 + i as f64, Some(attrs));
    }

    use opentelemetry::trace::Span as _;
    _span.end();

    shutdown_telemetry().expect("shutdown failed");
    println!("signals emitted run_id={run_id}");
}

#[cfg(not(feature = "otel"))]
fn main() {
    eprintln!("openobserve_01_emit_all_signals requires --features otel");
    std::process::exit(1);
}
