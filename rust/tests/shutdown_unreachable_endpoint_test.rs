// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Regression: `shutdown_telemetry()` must return promptly when the OTLP
//! log endpoint is unreachable.
//!
//! Mirrors the Python/TS/Go regressions. Without the bounded-shutdown
//! deadline (PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS) the OTel SDK's
//! `LoggerProvider::force_flush`/`shutdown` can sit in its internal retry
//! loop indefinitely against a closed-port collector.

#![cfg(feature = "otel")]

use std::net::TcpListener;
use std::time::{Duration, Instant};

use provide_telemetry::testing::acquire_test_state_lock;
use provide_telemetry::{setup_telemetry, shutdown_telemetry};

fn reserve_closed_port() -> u16 {
    let listener = TcpListener::bind("127.0.0.1:0").expect("listen on 127.0.0.1:0");
    let port = listener
        .local_addr()
        .expect("local_addr should succeed")
        .port();
    drop(listener); // close, so connects refuse instantly
    port
}

fn restore_var(key: &str, previous: Option<String>) {
    match previous {
        Some(value) => std::env::set_var(key, value),
        None => std::env::remove_var(key),
    }
}

#[test]
fn shutdown_telemetry_returns_within_deadline_with_unreachable_endpoint() {
    let _guard = acquire_test_state_lock();
    let _ = shutdown_telemetry();
    provide_telemetry::otel::_reset_otel_for_tests();

    let endpoint = format!("http://127.0.0.1:{}/", reserve_closed_port());
    let endpoint_key = "OTEL_EXPORTER_OTLP_ENDPOINT";
    let shutdown_key = "PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS";
    let trace_key = "PROVIDE_TRACE_ENABLED";
    let metrics_key = "PROVIDE_METRICS_ENABLED";

    let prev_endpoint = std::env::var(endpoint_key).ok();
    let prev_shutdown = std::env::var(shutdown_key).ok();
    let prev_trace = std::env::var(trace_key).ok();
    let prev_metrics = std::env::var(metrics_key).ok();

    std::env::set_var(endpoint_key, &endpoint);
    // 250ms deadline: pre-fix the OTel SDK's batch processor flush could
    // sit on the unreachable endpoint until its per-export timeout fired
    // (10s default). 250ms gives the bounded path room to fire and the
    // overall test wall time stays well under 2s even with noise.
    std::env::set_var(shutdown_key, "0.25");
    // Disable trace+metrics so only the logs OTLP path is exercised;
    // mirrors the cross-language pattern that proves disabling those is
    // insufficient on its own.
    std::env::set_var(trace_key, "false");
    std::env::set_var(metrics_key, "false");

    setup_telemetry().expect("setup should succeed even with unreachable endpoint");

    let started = Instant::now();
    shutdown_telemetry().expect("shutdown should return cleanly");
    let elapsed = started.elapsed();

    provide_telemetry::otel::_reset_otel_for_tests();
    restore_var(endpoint_key, prev_endpoint);
    restore_var(shutdown_key, prev_shutdown);
    restore_var(trace_key, prev_trace);
    restore_var(metrics_key, prev_metrics);

    // 250ms deadline + scheduling noise. A regression in the bounded
    // helper would push this well past the threshold.
    assert!(
        elapsed < Duration::from_secs(2),
        "shutdown_telemetry took {elapsed:?} with unreachable endpoint, expected <2s",
    );
}

#[test]
fn disable_log_otlp_avoids_provider_install_and_keeps_shutdown_fast() {
    let _guard = acquire_test_state_lock();
    let _ = shutdown_telemetry();
    provide_telemetry::otel::_reset_otel_for_tests();

    let endpoint = format!("http://127.0.0.1:{}/", reserve_closed_port());
    let endpoint_key = "OTEL_EXPORTER_OTLP_ENDPOINT";
    let enabled_key = "PROVIDE_LOG_OTLP_ENABLED";
    let trace_key = "PROVIDE_TRACE_ENABLED";
    let metrics_key = "PROVIDE_METRICS_ENABLED";

    let prev_endpoint = std::env::var(endpoint_key).ok();
    let prev_enabled = std::env::var(enabled_key).ok();
    let prev_trace = std::env::var(trace_key).ok();
    let prev_metrics = std::env::var(metrics_key).ok();

    std::env::set_var(endpoint_key, &endpoint);
    std::env::set_var(enabled_key, "false");
    std::env::set_var(trace_key, "false");
    std::env::set_var(metrics_key, "false");

    setup_telemetry().expect("setup should succeed with otlp_enabled=false");

    let started = Instant::now();
    shutdown_telemetry().expect("shutdown should return cleanly");
    let elapsed = started.elapsed();

    provide_telemetry::otel::_reset_otel_for_tests();
    restore_var(endpoint_key, prev_endpoint);
    restore_var(enabled_key, prev_enabled);
    restore_var(trace_key, prev_trace);
    restore_var(metrics_key, prev_metrics);

    assert!(
        elapsed < Duration::from_secs(1),
        "shutdown_telemetry took {elapsed:?} with OTLP logs disabled, expected <1s",
    );
}
