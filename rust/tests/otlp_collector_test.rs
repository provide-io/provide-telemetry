// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#![cfg(feature = "otel")]

use std::env;

use provide_telemetry::testing::{acquire_test_state_lock, reset_telemetry_state};
use provide_telemetry::{counter, get_logger, setup_telemetry, shutdown_telemetry, trace};

#[test]
fn otlp_collector_smoke() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    if env::var("PROVIDE_TEST_OTLP_ENDPOINT").is_err() {
        return;
    }

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
    reset_telemetry_state();
}
