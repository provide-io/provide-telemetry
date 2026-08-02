// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

//! Prove `flush_telemetry(None)` puts records on the wire without tearing providers down.
//!
//! Why a standalone process rather than a case in the OTLP integration test: the
//! collector is verified by grepping its debug log after the run, which cannot
//! tell *when* a record arrived. If this process also called
//! `shutdown_telemetry(None)`, shutdown's own drain would be an equally good
//! explanation for anything that showed up, and the check would pass with flush
//! completely broken.
//!
//! So this exits without shutting down. Every signal named below can only have
//! reached the collector because flush sent it.
//!
//! It also emits a second batch after the flush and asserts the providers are
//! still installed, which is the other half of the contract — flush drains, it
//! does not tear down.

fn fail(message: &str) -> ! {
    eprintln!("flush-collector-probe: FAIL — {message}");
    std::process::exit(1);
}

fn main() {
    let Ok(endpoint) = std::env::var("PROVIDE_TEST_OTLP_ENDPOINT") else {
        eprintln!("flush-collector-probe: PROVIDE_TEST_OTLP_ENDPOINT unset; skipping");
        return;
    };

    std::env::set_var(
        "PROVIDE_TELEMETRY_SERVICE_NAME",
        "provide-telemetry-rust-integration",
    );
    std::env::set_var("PROVIDE_TRACE_ENABLED", "true");
    std::env::set_var("PROVIDE_METRICS_ENABLED", "true");
    std::env::set_var(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        format!("{endpoint}/v1/traces"),
    );
    std::env::set_var(
        "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
        format!("{endpoint}/v1/metrics"),
    );
    std::env::set_var(
        "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
        format!("{endpoint}/v1/logs"),
    );

    if provide_telemetry::setup_telemetry(None).is_err() {
        fail("setup_telemetry failed");
    }

    let before = provide_telemetry::get_runtime_status();
    if !(before.providers.logs && before.providers.traces && before.providers.metrics) {
        fail("providers not installed before flush");
    }

    let requests = provide_telemetry::counter("integration.flush.requests", None, Some("1"));

    // Batch one — only a working flush can deliver this, since we never shut down.
    provide_telemetry::trace("integration.flush.span", || {
        provide_telemetry::get_logger(Some("integration.flush")).info("integration.flush.log");
        requests.add(1.0, None);
    });

    if provide_telemetry::flush_telemetry(None).is_err() {
        fail("flush_telemetry(None) reported an incomplete drain against a reachable collector");
    }

    // Flush drains; it must not tear down.
    let after = provide_telemetry::get_runtime_status();
    if !(after.providers.logs && after.providers.traces && after.providers.metrics) {
        fail("flush tore providers down");
    }
    if !after.setup_done {
        fail("flush cleared setup state");
    }

    provide_telemetry::trace("integration.flush.after.span", || {
        provide_telemetry::get_logger(Some("integration.flush"))
            .info("integration.flush.after.log");
        requests.add(1.0, None);
    });

    if provide_telemetry::flush_telemetry(None).is_err() {
        fail("a second flush_telemetry(None) reported an incomplete drain; flush is not repeatable");
    }

    eprintln!("flush-collector-probe: OK — flushed twice, providers still installed");
    // Deliberately no shutdown_telemetry(None): see the module comment.
}
