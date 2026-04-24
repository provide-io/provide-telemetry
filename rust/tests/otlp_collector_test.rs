// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#![cfg(feature = "otel")]

use std::env;

use std::time::Duration;

use provide_telemetry::testing::{acquire_test_state_lock, reset_telemetry_state};
use provide_telemetry::{counter, get_logger, setup_telemetry, shutdown_telemetry, trace};
use tokio::runtime::Builder;

const OTLP_COLLECTOR_ENV_KEYS: &[&str] = &[
    "PROVIDE_TELEMETRY_SERVICE_NAME",
    "PROVIDE_TRACE_ENABLED",
    "PROVIDE_METRICS_ENABLED",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
];

fn with_collector_env(endpoint: &str, test: impl FnOnce()) {
    let mut snapshot = Vec::with_capacity(OTLP_COLLECTOR_ENV_KEYS.len());
    for key in OTLP_COLLECTOR_ENV_KEYS {
        snapshot.push(((*key).to_string(), env::var(key).ok()));
    }

    // SAFETY: tests are serialised via acquire_test_state_lock at callsites.
    unsafe {
        let logs_endpoint = format!("{endpoint}/v1/logs");
        let traces_endpoint = format!("{endpoint}/v1/traces");
        let metrics_endpoint = format!("{endpoint}/v1/metrics");
        env::set_var(
            "PROVIDE_TELEMETRY_SERVICE_NAME",
            "provide-telemetry-rust-integration",
        );
        env::set_var("PROVIDE_TRACE_ENABLED", "true");
        env::set_var("PROVIDE_METRICS_ENABLED", "true");
        env::set_var("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint);
        env::set_var("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", logs_endpoint);
        env::set_var("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", traces_endpoint);
        env::set_var("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", metrics_endpoint);
    }

    test();

    // SAFETY: tests are serialised via acquire_test_state_lock at callsites.
    unsafe {
        for (key, value) in snapshot {
            match value {
                Some(value) => env::set_var(key, value),
                None => env::remove_var(key),
            }
        }
    }
}

#[test]
fn otlp_collector_smoke() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    let Ok(endpoint) = env::var("PROVIDE_TEST_OTLP_ENDPOINT") else {
        eprintln!("PROVIDE_TEST_OTLP_ENDPOINT not set — skipping OTLP collector test");
        return;
    };

    with_collector_env(&endpoint, || {
        // OTel's HTTP exporter dispatches its background BSP/PMR/LRP work via the
        // ambient tokio runtime. Use current_thread to keep all task progress
        // tied to a single thread the test can yield from — multi_thread caused
        // the BSP background task to exit immediately (channel closed before
        // any spans were enqueued).
        let runtime = Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("tokio runtime");

        runtime.block_on(async {
            eprintln!("[otlp_collector_smoke] before setup_telemetry");
            let cfg = setup_telemetry().expect("setup_telemetry should succeed");
            eprintln!(
                "[otlp_collector_smoke] after setup_telemetry: tracing.enabled={} tracing.endpoint={:?} metrics.enabled={} metrics.endpoint={:?}",
                cfg.tracing.enabled,
                cfg.tracing.otlp_endpoint,
                cfg.metrics.enabled,
                cfg.metrics.otlp_endpoint,
            );

            let requests = counter(
                "integration.collector.requests",
                Some("collector-backed integration smoke"),
                Some("1"),
            );
            let logger = get_logger(Some("integration.collector"));
            trace("integration.collector.span", || {
                logger.info("integration.collector.log");
                requests.add(1.0, None);
            });

            // Let the BSP/PMR/LRP background tasks observe the queued items.
            // Without this, BatchSpanProcessor's scheduled export hasn't fired
            // yet and force_flush below races with the spawn.
            tokio::time::sleep(Duration::from_millis(200)).await;

            eprintln!("[otlp_collector_smoke] before shutdown_telemetry");
            shutdown_telemetry().expect("shutdown_telemetry should succeed");
            eprintln!("[otlp_collector_smoke] after shutdown_telemetry");

            // Hold the runtime open briefly so any in-flight export tasks
            // spawned by shutdown can complete their HTTP POST to the collector
            // before the runtime is dropped (which would cancel them).
            tokio::time::sleep(Duration::from_secs(2)).await;
        });
    });

    reset_telemetry_state();
}
