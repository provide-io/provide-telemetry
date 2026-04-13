// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// Emits signals via setup_telemetry(), then polls OpenObserve to verify all
// three signal types (logs, traces, metrics) were actually ingested.
//
// Required env vars:
//   OPENOBSERVE_URL      — e.g. http://localhost:5080/api/default
//   OPENOBSERVE_USER     — e.g. admin@provide.test
//   OPENOBSERVE_PASSWORD — e.g. Complexpass#123
//   OTEL_EXPORTER_OTLP_ENDPOINT — same base URL as OPENOBSERVE_URL
//   OTEL_EXPORTER_OTLP_HEADERS  — Authorization=Basic <base64>
//   PROVIDE_TELEMETRY_SERVICE_NAME — e.g. provide-telemetry-rust-examples

#[cfg(feature = "otel")]
#[path = "support/openobserve_shared.rs"]
mod openobserve_shared;

#[cfg(feature = "otel")]
fn main() {
    use opentelemetry::trace::{Span as _, Tracer as _};
    use provide_telemetry::{counter, histogram, setup_telemetry, shutdown_telemetry};
    use serde_json::Value;
    use std::collections::BTreeMap;
    use std::thread::sleep;
    use std::time::{Duration, SystemTime, UNIX_EPOCH};

    let result = (|| -> Result<(), String> {
        let base_url = openobserve_shared::require_env("OPENOBSERVE_URL")?;
        let user = openobserve_shared::require_env("OPENOBSERVE_USER")?;
        let password = openobserve_shared::require_env("OPENOBSERVE_PASSWORD")?;
        let names = openobserve_shared::signal_names(None);
        let endpoints = openobserve_shared::OpenObserveEndpoints::new(&base_url);
        let auth = openobserve_shared::auth_header(&user, &password);

        let start_us = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_micros() as u64
            - (2 * 60 * 60 * 1_000_000);
        let now_us = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_micros() as u64;

        // Count baseline before emitting
        let log_hits_before =
            openobserve_shared::search_hits(&endpoints, "logs", &auth, start_us, now_us)?
                .iter()
                .filter(|h| h.get("run_id").and_then(Value::as_str) == Some(names.run_id.as_str()))
                .count();
        let trace_hits_before =
            openobserve_shared::search_hits(&endpoints, "traces", &auth, start_us, now_us)?
                .iter()
                .filter(|h| {
                    h.get("operation_name").and_then(Value::as_str)
                        == Some(names.trace_name.as_str())
                })
                .count();
        let metrics_before = openobserve_shared::metric_stream_names(&endpoints, &auth)?
            .contains(&names.metric_stream);

        println!(
            "before={{\"logs\":{log_hits_before},\"metrics_stream_present\":{metrics_before},\"traces\":{trace_hits_before}}}"
        );

        // Emit all signals through the library API.
        setup_telemetry().map_err(|e| format!("setup_telemetry failed: {e}"))?;

        // Traces: use the global OTel tracer installed by setup_telemetry().
        let tracer = opentelemetry::global::tracer("example.openobserve");
        let mut span = tracer.start(names.trace_name.clone());

        let requests = counter(names.metric_name.as_str(), None, None);
        let latency = histogram(
            format!("example.openobserve.latency.{}", names.run_id).as_str(),
            None,
            Some("ms"),
        );

        for i in 0..5i64 {
            // Structured tracing::info! fields become OTel log attributes.
            tracing::info!(
                run_id = %names.run_id,
                event = names.otlp_log_event.as_str(),
                iteration = i,
                "openobserve otlp log",
            );

            let mut attrs = BTreeMap::new();
            attrs.insert("run_id".to_string(), names.run_id.clone());
            attrs.insert("iteration".to_string(), i.to_string());
            requests.add(1.0, Some(attrs.clone()));
            latency.record(50.0 + i as f64, Some(attrs));
        }

        // End span before shutdown so it gets exported.
        span.end();
        shutdown_telemetry().map_err(|e| format!("shutdown_telemetry failed: {e}"))?;

        // Poll OpenObserve for ingestion
        let deadline = std::time::Instant::now() + Duration::from_secs(30);
        let mut after_logs = log_hits_before;
        let mut after_traces = trace_hits_before;
        let mut after_metrics = metrics_before;

        while std::time::Instant::now() < deadline {
            let end_us = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_micros() as u64;

            after_logs =
                openobserve_shared::search_hits(&endpoints, "logs", &auth, start_us, end_us)?
                    .iter()
                    .filter(|h| {
                        h.get("run_id").and_then(Value::as_str) == Some(names.run_id.as_str())
                    })
                    .count();
            after_traces =
                openobserve_shared::search_hits(&endpoints, "traces", &auth, start_us, end_us)?
                    .iter()
                    .filter(|h| {
                        h.get("operation_name").and_then(Value::as_str)
                            == Some(names.trace_name.as_str())
                    })
                    .count();
            after_metrics = openobserve_shared::metric_stream_names(&endpoints, &auth)?
                .contains(&names.metric_stream);

            if after_logs > log_hits_before && after_traces > trace_hits_before && after_metrics {
                break;
            }
            sleep(Duration::from_secs(1));
        }

        println!(
            "after={{\"logs\":{after_logs},\"metrics_stream_present\":{after_metrics},\"traces\":{after_traces}}}"
        );

        let mut missing = Vec::new();
        if after_logs <= log_hits_before {
            missing.push("logs");
        }
        if !after_metrics {
            missing.push("metrics");
        }
        if after_traces <= trace_hits_before {
            missing.push("traces");
        }
        if !missing.is_empty() {
            return Err(format!(
                "ingestion did not increase for: {}",
                missing.join(", ")
            ));
        }

        println!("verification passed");
        Ok(())
    })();

    if let Err(err) = result {
        eprintln!("{err}");
        std::process::exit(1);
    }
}

#[cfg(not(feature = "otel"))]
fn main() {
    eprintln!("openobserve_02_verify_ingestion requires --features otel");
    std::process::exit(1);
}
