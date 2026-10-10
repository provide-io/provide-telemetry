// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

//! Record the push_ingestion instruments and push them to Prometheus over OTLP.
//!
//! Tier 1 of the Prometheus contract: no Prometheus-specific code, only the
//! ordinary OTLP metrics exporter pointed at a Prometheus 3 OTLP receiver. The
//! instruments are listed in spec/prometheus_fixtures.yaml (push_ingestion); the
//! E2E test in e2e/test_prometheus_push_e2e.py queries them back.
//!
//! Inputs (environment):
//!   OTEL_EXPORTER_OTLP_METRICS_ENDPOINT   e.g. http://127.0.0.1:9090/api/v1/otlp/v1/metrics
//!   PROVIDE_TELEMETRY_SERVICE_NAME        becomes the Prometheus job label
//!   PROVIDE_PROM_PROBE_PREFIX             dotted metric-name prefix for this run
//!
//! Run with `cargo run --features otel --example prometheus_push_probe`.

use std::collections::BTreeMap;

fn attrs(key: &str, value: &str) -> Option<BTreeMap<String, String>> {
    Some(BTreeMap::from([(key.to_string(), value.to_string())]))
}

fn main() {
    let (Ok(prefix), Ok(_)) = (
        std::env::var("PROVIDE_PROM_PROBE_PREFIX"),
        std::env::var("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"),
    ) else {
        eprintln!("prometheus-push-probe: endpoint or prefix unset");
        std::process::exit(2);
    };
    if std::env::var("PROVIDE_TRACE_ENABLED").is_err() {
        std::env::set_var("PROVIDE_TRACE_ENABLED", "false");
    }
    if let Err(err) = provide_telemetry::setup_telemetry(None) {
        eprintln!("prometheus-push-probe: FAIL — setup: {err}");
        std::process::exit(1);
    }

    provide_telemetry::counter(&format!("{prefix}.requests"), None, None)
        .add(3.0, attrs("route", "/a"));
    provide_telemetry::histogram(&format!("{prefix}.request.duration"), None, Some("ms"))
        .record(12.0, attrs("route", "/a"));
    provide_telemetry::gauge(&format!("{prefix}.cpu.utilization"), None, Some("1"))
        .set(1.0, attrs("core", "0"));

    // Shutdown drains the periodic reader, which is what puts the data on the wire.
    if let Err(err) = provide_telemetry::shutdown_telemetry(None) {
        eprintln!("prometheus-push-probe: FAIL — shutdown: {err}");
        std::process::exit(1);
    }
    eprintln!("prometheus-push-probe: OK");
}
