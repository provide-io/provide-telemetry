// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Both directions of `async_blocking_risk_*`.
//!
//! The counter has to move when a synchronous drain is entered from inside a
//! Tokio runtime and stay put when it is not — a counter that only ever goes up
//! is as useless as one that never does, because neither tells an operator
//! anything about the call they are looking at.

use super::{logs, metrics, traces};

use crate::health::get_health_snapshot;
use crate::testing::{acquire_test_state_lock, reset_telemetry_state};
use opentelemetry_sdk::logs::SdkLoggerProvider;
use opentelemetry_sdk::metrics::SdkMeterProvider;
use opentelemetry_sdk::trace::SdkTracerProvider;

/// Install traces and metrics but deliberately *not* logs, so the same run
/// pins the "signal we do not own stays at zero" half of the contract.
fn install_traces_and_metrics() {
    traces::install_tracer_provider_for_tests(SdkTracerProvider::builder().build());
    metrics::install_meter_provider_for_tests(SdkMeterProvider::builder().build());
}

/// The reachable caller: an async application calling the synchronous
/// `flush_telemetry`/`shutdown_telemetry` from inside its runtime. Both park a
/// Tokio worker for the length of the drain, and both must say so.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn a_drain_entered_from_inside_a_tokio_runtime_is_counted_per_owned_signal() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    install_traces_and_metrics();

    crate::flush_telemetry(Some(0.5)).expect("an empty provider drains inside its deadline");

    let after_flush = get_health_snapshot();
    assert_eq!(after_flush.async_blocking_risk_traces, 1);
    assert_eq!(after_flush.async_blocking_risk_metrics, 1);
    // No logger provider was installed, so no logs drain ran and nothing about
    // logs was stalled. Counting it anyway would point an operator at the wrong
    // exporter.
    assert_eq!(after_flush.async_blocking_risk_logs, 0);

    crate::shutdown_telemetry(Some(0.5)).expect("shutdown always reports success");

    // Per call, not per process: the teardown parked the worker a second time.
    let after_shutdown = get_health_snapshot();
    assert_eq!(after_shutdown.async_blocking_risk_traces, 2);
    assert_eq!(after_shutdown.async_blocking_risk_metrics, 2);
    assert_eq!(after_shutdown.async_blocking_risk_logs, 0);

    reset_telemetry_state();
}

/// The same two calls off any runtime. Blocking a plain thread is what
/// `flush_telemetry` is for, so nothing here is a risk and nothing may be
/// counted — otherwise the metric fires for every ordinary shutdown and an
/// operator learns to ignore it.
#[test]
fn a_drain_entered_from_an_ordinary_thread_is_not_counted() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    install_traces_and_metrics();
    // A logger provider too: on this path *no* signal may be counted, owned or
    // not, so pin all three rather than the two the async test can pin.
    logs::install_logger_provider_for_tests(SdkLoggerProvider::builder().build());

    crate::flush_telemetry(Some(0.5)).expect("an empty provider drains inside its deadline");
    crate::shutdown_telemetry(Some(0.5)).expect("shutdown always reports success");

    let snapshot = get_health_snapshot();
    assert_eq!(snapshot.async_blocking_risk_logs, 0);
    assert_eq!(snapshot.async_blocking_risk_traces, 0);
    assert_eq!(snapshot.async_blocking_risk_metrics, 0);

    reset_telemetry_state();
}

/// Inside a runtime but with nothing of ours installed: the drain still parks
/// the worker briefly, but it drained nothing, so there is no signal to charge.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn a_drain_with_no_provider_of_ours_installed_charges_no_signal() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    crate::flush_telemetry(Some(0.5)).expect("nothing installed is a drained state");

    let snapshot = get_health_snapshot();
    assert_eq!(snapshot.async_blocking_risk_logs, 0);
    assert_eq!(snapshot.async_blocking_risk_traces, 0);
    assert_eq!(snapshot.async_blocking_risk_metrics, 0);

    reset_telemetry_state();
}
