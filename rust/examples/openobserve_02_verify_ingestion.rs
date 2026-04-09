// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#[cfg(feature = "otel")]
use std::thread::sleep;
#[cfg(feature = "otel")]
use std::time::{Duration, SystemTime, UNIX_EPOCH};

#[cfg(feature = "otel")]
use serde_json::Value;

#[cfg(feature = "otel")]
#[path = "support/openobserve_shared.rs"]
mod openobserve_shared;

#[cfg(feature = "otel")]
fn count_log_hits(hits: &[Value], run_id: &str, otlp_event: &str, json_event: &str) -> usize {
    hits.iter()
        .filter(|hit| {
            hit.get("run_id").and_then(Value::as_str) == Some(run_id)
                && matches!(
                    hit.get("event").and_then(Value::as_str),
                    Some(event) if event == otlp_event || event == json_event
                )
        })
        .count()
}

#[cfg(feature = "otel")]
fn count_trace_hits(hits: &[Value], trace_name: &str) -> usize {
    hits.iter()
        .filter(|hit| hit.get("operation_name").and_then(Value::as_str) == Some(trace_name))
        .count()
}

#[cfg(feature = "otel")]
fn main() {
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
        let now_us =
            SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_micros() as u64;
        let before_logs = count_log_hits(
            &openobserve_shared::search_hits(&endpoints, "logs", &auth, start_us, now_us)?,
            &names.run_id,
            &names.otlp_log_event,
            &names.json_log_event,
        );
        let before_traces = count_trace_hits(
            &openobserve_shared::search_hits(&endpoints, "traces", &auth, start_us, now_us)?,
            &names.trace_name,
        );
        let before_metrics = openobserve_shared::metric_stream_names(&endpoints, &auth)?
            .contains(&names.metric_stream);

        println!(
            "before={{\"logs\":{before_logs},\"metrics_stream_present\":{before_metrics},\"traces\":{before_traces}}}"
        );

        openobserve_shared::emit_all_signals(
            &endpoints,
            &auth,
            &names,
            "provide-telemetry-rust-examples",
        )?;

        let deadline = std::time::Instant::now() + Duration::from_secs(30);
        let mut after_logs = before_logs;
        let mut after_traces = before_traces;
        let mut after_metrics = before_metrics;
        while std::time::Instant::now() < deadline {
            let end_us =
                SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_micros() as u64;
            after_logs = count_log_hits(
                &openobserve_shared::search_hits(&endpoints, "logs", &auth, start_us, end_us)?,
                &names.run_id,
                &names.otlp_log_event,
                &names.json_log_event,
            );
            after_traces = count_trace_hits(
                &openobserve_shared::search_hits(&endpoints, "traces", &auth, start_us, end_us)?,
                &names.trace_name,
            );
            after_metrics = openobserve_shared::metric_stream_names(&endpoints, &auth)?
                .contains(&names.metric_stream);

            if after_logs > before_logs && after_traces > before_traces && after_metrics {
                break;
            }
            sleep(Duration::from_secs(1));
        }

        println!(
            "after={{\"logs\":{after_logs},\"metrics_stream_present\":{after_metrics},\"traces\":{after_traces}}}"
        );

        let mut missing = Vec::new();
        if after_logs <= before_logs {
            missing.push("logs");
        }
        if !after_metrics {
            missing.push("metrics");
        }
        if after_traces <= before_traces {
            missing.push("traces");
        }
        if !missing.is_empty() {
            return Err(format!("ingestion did not increase for: {}", missing.join(", ")));
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
