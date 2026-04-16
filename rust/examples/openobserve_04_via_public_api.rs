// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Emit a span via the public `setup_telemetry()` + `trace()` API and
//! verify that real OTLP export reaches an OpenObserve collector.
//!
//! Unlike `openobserve_01_emit_all_signals`, which constructs the OTel
//! SDK by hand, this example exercises ONLY the `provide_telemetry`
//! public surface — proving that the integration wired up in
//! `otel/traces.rs` actually delivers spans to a collector when called
//! through the same path application code would use.
//!
//! Required env vars:
//! - `OTEL_EXPORTER_OTLP_ENDPOINT` (e.g. `http://localhost:5080/api/default`)
//! - `OTEL_EXPORTER_OTLP_HEADERS` for OpenObserve auth
//!   (e.g. `Authorization=Basic%20<base64(user:pass)>`)
//! - `PROVIDE_TELEMETRY_SERVICE_NAME` (optional; defaults to
//!   `provide-service`)
//!
//! Build: `cargo build --features otel --example openobserve_04_via_public_api`
//! Run:   `cargo run   --features otel --example openobserve_04_via_public_api`
//!
//! The example prints the trace_id and span_id of the emitted span so
//! you can search for them in OpenObserve.

#[cfg(feature = "otel")]
fn main() {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .expect("build tokio runtime");

    runtime.block_on(async {
        // Standard public-API entry point. Reads the OTEL_EXPORTER_OTLP_*
        // env vars via TelemetryConfig::from_env() inside.
        let cfg = provide_telemetry::setup_telemetry().expect("setup_telemetry");
        println!(
            "setup ok service={} env={}",
            cfg.service_name, cfg.environment
        );

        // Emit a span via the public trace() entry point. With OTel
        // installed and the global TracerProvider wired by setup_otel,
        // this routes through SdkTracerProvider -> BatchSpanProcessor ->
        // OTLP HTTP exporter to the configured endpoint.
        let _ = provide_telemetry::trace("example.public_api.work", || {
            let ctx = provide_telemetry::get_trace_context();
            let trace_id = ctx
                .get("trace_id")
                .and_then(Clone::clone)
                .unwrap_or_default();
            let span_id = ctx
                .get("span_id")
                .and_then(Clone::clone)
                .unwrap_or_default();
            println!("emitted trace_id={trace_id} span_id={span_id}");
            // Tiny work payload so the span has measurable duration.
            std::thread::sleep(std::time::Duration::from_millis(5));
        });

        // Emit a counter increment + a histogram observation. With OTel
        // installed, these dual-emit: in-process state for tests +
        // OTLP push via the global MeterProvider on its 60s flush
        // interval (force_flush at shutdown).
        let counter = provide_telemetry::counter(
            "example.public_api.requests",
            Some("requests served by the probe"),
            Some("1"),
        );
        counter.add(1.0, None);
        let histogram = provide_telemetry::histogram(
            "example.public_api.latency_ms",
            Some("synthetic latency observation"),
            Some("ms"),
        );
        histogram.record(5.0, None);
        println!("emitted metric requests=1 latency=5ms");

        // Emit a log via the public Logger. With OTel installed, the
        // record dual-emits: stderr (existing path) AND OTLP push via
        // the LoggerProvider.
        let logger = provide_telemetry::get_logger(Some("examples.public_api"));
        logger.info("example.public_api.log");
        println!("emitted log message=example.public_api.log");

        // Flush + tear down the providers so the batch processor exports
        // before the runtime is dropped.
        provide_telemetry::shutdown_telemetry().expect("shutdown_telemetry");
        println!("shutdown ok");
    });
}

#[cfg(not(feature = "otel"))]
fn main() {
    eprintln!("openobserve_04_via_public_api requires --features otel");
    std::process::exit(1);
}
