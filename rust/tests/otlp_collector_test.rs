// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#![cfg(feature = "otel")]

use std::env;

use provide_telemetry::testing::{acquire_test_state_lock, reset_telemetry_state};
use provide_telemetry::{counter, get_logger, setup_telemetry, shutdown_telemetry, trace};
use tokio::runtime::Builder;

#[test]
fn otlp_collector_smoke() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    let Ok(endpoint) = env::var("PROVIDE_TEST_OTLP_ENDPOINT") else {
        eprintln!("PROVIDE_TEST_OTLP_ENDPOINT not set — skipping OTLP collector test");
        return;
    };

    // Enable each signal explicitly. Without these, the OTel install paths
    // bail out as no-ops and nothing is exported to the collector — the
    // workflow can't infer them just from the endpoint being set. Mirrors
    // the Go test's `t.Setenv("PROVIDE_TRACE_ENABLED", "true")` pattern.
    // SAFETY: tests are serialised via acquire_test_state_lock above, so
    // mutating process-global env here cannot race other test threads.
    unsafe {
        env::set_var(
            "PROVIDE_TELEMETRY_SERVICE_NAME",
            "provide-telemetry-rust-integration",
        );
        env::set_var("PROVIDE_TRACE_ENABLED", "true");
        env::set_var("PROVIDE_METRICS_ENABLED", "true");
        env::set_var("OTEL_EXPORTER_OTLP_ENDPOINT", &endpoint);
    }

    // OTel's HTTP exporter dispatches its background BSP/PMR/LRP work via the
    // ambient tokio runtime. Without one, force_flush + shutdown queue exports
    // that are never executed, the test exits in 0.00s, and the collector
    // receives nothing. Wrap setup → emit → shutdown in a multi-thread tokio
    // runtime so the exporter task pool can actually run.
    let runtime = Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()
        .expect("tokio runtime");

    runtime.block_on(async {
        setup_telemetry().expect("setup_telemetry should succeed");

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

        shutdown_telemetry().expect("shutdown_telemetry should succeed");
    });

    reset_telemetry_state();
}
