// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

//! Serve a counter and an observable gauge on the standalone listener until stdin closes.
//!
//! Tier 3 of the Prometheus contract: e2e/test_prometheus_scrape_e2e.py starts
//! this with OTEL_METRICS_EXPORTER=prometheus and PROVIDE_METRICS_PROMETHEUS_LISTEN=true
//! (plus a web config for the secured run), waits for "ready" on stdout, and
//! checks what a real Prometheus scraped.
//!
//! Run with `cargo run --features prometheus-listener --example prometheus_scrape_probe`.

use std::io::Read;

use provide_telemetry::{
    counter, get_health_snapshot, observable_gauge, setup_telemetry, shutdown_telemetry,
    Observation,
};

fn main() {
    if std::env::var("PROVIDE_TRACE_ENABLED").is_err() {
        std::env::set_var("PROVIDE_TRACE_ENABLED", "false");
    }
    if let Err(err) = setup_telemetry(None) {
        eprintln!("prometheus-scrape-probe: FAIL — setup: {err}");
        std::process::exit(1);
    }
    if let Some(error) = get_health_snapshot().setup_error {
        eprintln!("prometheus-scrape-probe: FAIL — {error}");
        std::process::exit(1);
    }
    counter("e2e.scrape.requests", None, None).add(3.0, None);
    let _temperature = observable_gauge(
        "e2e.scrape.temperature",
        || vec![Observation::new(41.5)],
        None,
        Some("Cel"),
    );
    println!("ready");
    let _ = std::io::stdin().read_to_end(&mut Vec::new());
    let _ = shutdown_telemetry(None);
}
