// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

//! Serve a Prometheus scrape endpoint from the SDK.
//!
//! Demonstrates:
//! - Enabling the Prometheus pull reader with `OTEL_METRICS_EXPORTER=prometheus`
//!   (use `otlp,prometheus` to push over OTLP as well)
//! - `metrics_handler(method, accept)`: the framework-neutral Tier 2 handler a
//!   host calls from its own HTTP route and copies status, headers and body from
//! - A counter and a histogram with units, plus an observable gauge whose
//!   callback runs on every scrape
//! - One in-process scrape, showing the Prometheus names the SDK renders: dots
//!   become underscores, counters gain `_total`, units become suffixes
//! - The SDK's own health as `provide_telemetry_*` series in the same scrape
//!
//! Runs offline: the handler is called directly, so no port is bound. The pull
//! reader lives in the `otel` feature; for the standalone listener
//! (`PROVIDE_METRICS_PROMETHEUS_LISTEN=true`) enable `prometheus-listener`.
//!
//! Run with `cargo run --features otel --example telemetry_15_prometheus_metrics`.

#[cfg(feature = "otel")]
fn run() -> Result<(), String> {
    use std::collections::{BTreeMap, HashMap};

    use provide_telemetry::{
        counter, histogram, metrics_handler, observable_gauge, setup_telemetry, shutdown_telemetry,
        Observation, TelemetryConfig,
    };

    fn labels(key: &str, value: &str) -> Option<BTreeMap<String, String>> {
        Some(BTreeMap::from([(key.to_string(), value.to_string())]))
    }

    fn type_names(body: &str) -> Vec<&str> {
        body.lines()
            .filter_map(|line| line.strip_prefix("# TYPE "))
            .filter_map(|rest| rest.split_whitespace().next())
            .collect()
    }

    println!("Rust Prometheus Metrics Demo");

    // Enable the pull reader. Prometheus alone keeps the example offline.
    let env = HashMap::from([
        (
            "PROVIDE_TELEMETRY_SERVICE_NAME".to_string(),
            "prometheus-example".to_string(),
        ),
        (
            "OTEL_METRICS_EXPORTER".to_string(),
            "prometheus".to_string(),
        ),
        ("PROVIDE_TRACE_ENABLED".to_string(), "false".to_string()),
    ]);
    let config = TelemetryConfig::from_map(&env).map_err(|err| err.to_string())?;
    setup_telemetry(Some(config)).map_err(|err| err.to_string())?;
    println!("OTEL_METRICS_EXPORTER=prometheus -> pull reader attached");

    println!("\nRecording instruments:");
    counter("example.prom.requests", Some("Requests handled"), Some("1"))
        .add(3.0, labels("route", "/checkout"));
    println!("  counter   example.prom.requests (unit 1)    +3");
    let latency = histogram("example.prom.latency", Some("Request latency"), Some("ms"));
    for value in [12.5, 40.0, 87.5] {
        latency.record(value, labels("route", "/checkout"));
    }
    println!("  histogram example.prom.latency (unit ms)    12.5, 40.0, 87.5");
    let depth = observable_gauge(
        "example.prom.queue_depth",
        || {
            vec![Observation::with_attributes(
                7.0,
                BTreeMap::from([("queue".to_string(), "jobs".to_string())]),
            )]
        },
        Some("Jobs waiting"),
        Some("1"),
    );
    println!("  observable gauge example.prom.queue_depth   callback -> 7");

    // What a route handler would do: pass the method and Accept header in,
    // copy status, headers and body out.
    println!("\nGET /metrics (in-process metrics_handler call):");
    let response = metrics_handler("GET", Some("text/plain"));
    let content_type = response
        .headers
        .iter()
        .find(|(name, _)| *name == "content-type")
        .map_or("", |(_, value)| value.as_str());
    println!("  {}  {content_type}", response.status);
    let body = String::from_utf8_lossy(&response.body).into_owned();
    let names = type_names(&body);

    println!(
        "\nYour metrics, as Prometheus names them (ms -> _milliseconds, 1 -> _ratio, counter -> _total):"
    );
    for name in names.iter().filter(|n| n.starts_with("example_")) {
        println!("  {name}");
    }
    println!("\nSDK health series in the same scrape:");
    for name in names.iter().filter(|n| n.starts_with("provide_telemetry_")) {
        println!("  {name}");
    }
    if let Some(line) = body
        .lines()
        .find(|line| line.starts_with("example_prom_queue_depth"))
    {
        println!("\nObservable gauge sample: {line}");
    }

    depth.unregister();
    shutdown_telemetry(None).map_err(|err| err.to_string())?;
    let after = metrics_handler("GET", None);
    println!(
        "\nAfter shutdown the handler answers {}: {}",
        after.status,
        String::from_utf8_lossy(&after.body).trim()
    );
    println!("\nDone!");
    Ok(())
}

#[cfg(feature = "otel")]
fn main() {
    if let Err(err) = run() {
        eprintln!("prometheus metrics example failed: {err}");
        std::process::exit(1);
    }
}

#[cfg(not(feature = "otel"))]
fn main() {
    // The pull reader is part of the otel feature; without it the handler
    // only answers 503 naming that reason, so there is nothing to show.
    println!("telemetry_15_prometheus_metrics: rerun with --features otel to serve a scrape");
}
