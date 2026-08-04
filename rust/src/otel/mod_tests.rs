// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Tests for the OTel facade in `mod.rs`, split out to keep that file inside
//! the 500-line ceiling `scripts/check_max_loc.py` enforces.

#[cfg(feature = "otel")]
use super::bounded::MAX_DRAIN_SECONDS;
use super::*;

/// `Duration::from_secs_f64` panics on NaN, on ±inf, and past u64::MAX
/// seconds. `drain_deadline` must absorb all of those rather than let a
/// caller-supplied `timeout_seconds` abort the process from a shutdown path.
#[cfg(feature = "otel")]
#[test]
fn otel_test_drain_deadline_rejects_unusable_values() {
    assert_eq!(drain_deadline(f64::NAN), None);
    assert_eq!(drain_deadline(f64::INFINITY), None);
}

/// `<= 0` is a zero budget, not an opt-out: Python's `wait(0)` and
/// TypeScript's `setTimeout(..., 0)` abandon the drain immediately, and a
/// caller porting `flush(0)` from either must not get an unbounded
/// synchronous drain here instead — that is the SIGTERM hang the timeout
/// parameter exists to prevent.
#[cfg(feature = "otel")]
#[test]
fn otel_test_drain_deadline_treats_non_positive_values_as_a_zero_budget() {
    assert_eq!(drain_deadline(0.0), Some(std::time::Duration::ZERO));
    assert_eq!(drain_deadline(-1.5), Some(std::time::Duration::ZERO));
    assert_eq!(
        drain_deadline(f64::NEG_INFINITY),
        Some(std::time::Duration::ZERO)
    );
}

#[cfg(feature = "otel")]
#[test]
fn otel_test_drain_deadline_passes_through_and_clamps() {
    assert_eq!(
        drain_deadline(2.5),
        Some(std::time::Duration::from_secs_f64(2.5))
    );
    // f64::MAX seconds is well past what Duration can hold; clamping is what
    // keeps the conversion from panicking.
    assert_eq!(
        drain_deadline(f64::MAX),
        Some(std::time::Duration::from_secs_f64(MAX_DRAIN_SECONDS))
    );
    assert_eq!(
        drain_deadline(MAX_DRAIN_SECONDS - 1.0),
        Some(std::time::Duration::from_secs_f64(MAX_DRAIN_SECONDS - 1.0))
    );
}

/// The whole point of the guard: these arguments used to panic inside
/// `shutdown_telemetry`, aborting the process instead of draining.
#[cfg(feature = "otel")]
#[test]
fn otel_test_bounded_flush_survives_a_non_finite_caller_timeout() {
    assert!(bounded_flush("logs", Some(f64::NAN), || true));
    assert!(bounded_flush("traces", Some(f64::INFINITY), || true));
    assert!(!bounded_flush("metrics", Some(f64::MAX), || false));
}

#[cfg(not(feature = "otel"))]
#[test]
fn otel_test_installed_for_tests_is_false_without_feature() {
    assert!(!otel_installed_for_tests());
}

#[cfg(feature = "otel")]
#[test]
fn otel_test_installed_for_tests_matches_runtime_state_with_feature() {
    assert_eq!(otel_installed_for_tests(), otel_installed());
}

#[cfg(feature = "otel")]
#[test]
fn setup_otel_surfaces_tracer_exporter_errors() {
    let _guard = crate::testing::acquire_test_state_lock();
    crate::testing::reset_telemetry_state();

    let mut cfg = TelemetryConfig::default();
    cfg.tracing.otlp_endpoint = Some("ftp://collector:4317".to_string());
    cfg.exporter.traces_fail_open = false;

    let err = setup_otel(&cfg).expect_err("invalid tracing endpoint must fail setup");
    assert!(err.message.contains("scheme"));

    crate::testing::reset_telemetry_state();
}

#[cfg(feature = "otel")]
#[test]
fn setup_otel_surfaces_meter_exporter_errors_after_traces_short_circuit() {
    let _guard = crate::testing::acquire_test_state_lock();
    crate::testing::reset_telemetry_state();

    let mut cfg = TelemetryConfig::default();
    cfg.tracing.enabled = false;
    cfg.metrics.enabled = true;
    cfg.metrics.otlp_endpoint = Some("ftp://collector:4318".to_string());
    cfg.exporter.metrics_fail_open = false;

    let err = setup_otel(&cfg).expect_err("invalid metrics endpoint must fail setup");
    assert!(err.message.contains("scheme"));

    crate::testing::reset_telemetry_state();
}

#[cfg(feature = "otel")]
#[test]
fn setup_otel_surfaces_logger_exporter_errors_after_other_signals_short_circuit() {
    let _guard = crate::testing::acquire_test_state_lock();
    crate::testing::reset_telemetry_state();

    let mut cfg = TelemetryConfig::default();
    cfg.tracing.enabled = false;
    cfg.metrics.enabled = false;
    cfg.logging.otlp_endpoint = Some("ftp://collector:4318".to_string());
    cfg.exporter.logs_fail_open = false;

    let err = setup_otel(&cfg).expect_err("invalid logs endpoint must fail setup");
    assert!(err.message.contains("scheme"));

    crate::testing::reset_telemetry_state();
}

#[cfg(feature = "otel")]
#[test]
fn map_exporter_build_formats_signal_specific_errors() {
    let err = map_exporter_build::<(), _>(Err("boom"), "logs")
        .expect_err("fake exporter error should map");
    assert_eq!(err.message, "OTLP logs exporter build failed: boom");
}

// Kills: `||` -> `&&` in otel_installed. With AND, installing only one of the
// three providers makes otel_installed() return false; with OR (the original)
// any one provider is sufficient.
#[cfg(feature = "otel")]
#[tokio::test(flavor = "multi_thread", worker_threads = 1)]
async fn otel_installed_returns_true_when_only_tracer_provider_is_installed() {
    let _guard = crate::testing::acquire_test_state_lock();
    crate::testing::reset_telemetry_state();

    let mut cfg = TelemetryConfig::default();
    cfg.tracing.otlp_endpoint = Some("http://127.0.0.1:1/never".to_string());
    cfg.exporter.traces_fail_open = true;
    let resource = resource::build_resource(&cfg);
    traces::install_tracer_provider(&cfg, resource)
        .expect("tracer provider should install under fail_open");

    assert!(traces::tracer_provider_installed());
    assert!(!metrics::meter_provider_installed());
    assert!(!logs::logger_provider_installed());
    assert!(otel_installed());

    crate::testing::reset_telemetry_state();
}

#[cfg(feature = "otel")]
#[tokio::test(flavor = "multi_thread", worker_threads = 1)]
async fn otel_installed_returns_true_when_only_logger_provider_is_installed() {
    let _guard = crate::testing::acquire_test_state_lock();
    crate::testing::reset_telemetry_state();

    let mut cfg = TelemetryConfig::default();
    cfg.tracing.enabled = false;
    cfg.metrics.enabled = false;
    cfg.logging.otlp_endpoint = Some("http://127.0.0.1:1/never".to_string());
    cfg.exporter.logs_fail_open = true;
    let resource = resource::build_resource(&cfg);
    logs::install_logger_provider(&cfg, resource)
        .expect("logger provider should install under fail_open");

    assert!(!traces::tracer_provider_installed());
    assert!(!metrics::meter_provider_installed());
    assert!(logs::logger_provider_installed());
    assert!(otel_installed());

    _reset_otel_for_tests();
    assert!(!traces::tracer_provider_installed());
    assert!(!metrics::meter_provider_installed());
    assert!(!logs::logger_provider_installed());
    assert!(!otel_installed());

    crate::testing::reset_telemetry_state();
}
