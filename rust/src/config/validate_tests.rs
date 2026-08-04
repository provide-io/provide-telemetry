// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! An explicit config gets the same range checks a parsed one does.

use super::*;

fn valid() -> TelemetryConfig {
    TelemetryConfig::default()
}

#[test]
fn a_default_config_is_valid() {
    valid().validate().expect("defaults must validate");
}

#[test]
fn each_sampling_rate_is_rejected_above_one() {
    for (field, set) in [
        (
            "PROVIDE_SAMPLING_LOGS_RATE",
            (|cfg: &mut TelemetryConfig| cfg.sampling.logs_rate = 2.0) as fn(&mut TelemetryConfig),
        ),
        ("PROVIDE_SAMPLING_TRACES_RATE", |cfg| {
            cfg.sampling.traces_rate = 2.0
        }),
        ("PROVIDE_SAMPLING_METRICS_RATE", |cfg| {
            cfg.sampling.metrics_rate = 2.0
        }),
        ("PROVIDE_TRACE_SAMPLE_RATE", |cfg| {
            cfg.tracing.sample_rate = 2.0
        }),
    ] {
        let mut cfg = valid();
        set(&mut cfg);
        let err = cfg
            .validate()
            .expect_err("a rate above one must be rejected");
        assert!(
            err.message.contains(field) && err.message.contains("must be in [0, 1]"),
            "unexpected message for {field}: {}",
            err.message
        );
    }
}

#[test]
fn a_negative_sampling_rate_is_rejected() {
    let mut cfg = valid();
    cfg.sampling.logs_rate = -0.1;
    let err = cfg
        .validate()
        .expect_err("a negative rate must be rejected");
    assert!(err.message.contains("PROVIDE_SAMPLING_LOGS_RATE"));
}

#[test]
fn a_non_finite_sampling_rate_is_rejected() {
    // NaN fails every comparison, so a range check written as a negated
    // comparison would let it through and reach Duration::from_secs_f64.
    for rate in [f64::NAN, f64::INFINITY] {
        let mut cfg = valid();
        cfg.sampling.traces_rate = rate;
        cfg.validate()
            .expect_err("a non-finite rate must be rejected");
    }
}

#[test]
fn each_exporter_duration_is_rejected_when_negative() {
    for (field, set) in [
        (
            "PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS",
            (|cfg: &mut TelemetryConfig| cfg.exporter.logs_backoff_seconds = -1.0)
                as fn(&mut TelemetryConfig),
        ),
        ("PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS", |cfg| {
            cfg.exporter.traces_backoff_seconds = -1.0
        }),
        ("PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS", |cfg| {
            cfg.exporter.metrics_backoff_seconds = -1.0
        }),
        ("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS", |cfg| {
            cfg.exporter.logs_timeout_seconds = -1.0
        }),
        ("PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS", |cfg| {
            cfg.exporter.traces_timeout_seconds = -1.0
        }),
        ("PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS", |cfg| {
            cfg.exporter.metrics_timeout_seconds = -1.0
        }),
        ("PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS", |cfg| {
            cfg.exporter.logs_shutdown_timeout_seconds = -1.0
        }),
    ] {
        let mut cfg = valid();
        set(&mut cfg);
        let err = cfg
            .validate()
            .expect_err("a negative duration must be rejected");
        assert!(
            err.message.contains(field) && err.message.contains("must be >= 0"),
            "unexpected message for {field}: {}",
            err.message
        );
    }
}

#[test]
fn a_non_finite_exporter_duration_is_rejected() {
    let mut cfg = valid();
    cfg.exporter.logs_timeout_seconds = f64::NAN;
    cfg.validate()
        .expect_err("a non-finite duration must be rejected");
}

#[test]
fn the_boundaries_of_each_range_are_accepted() {
    let mut cfg = valid();
    cfg.sampling.logs_rate = 0.0;
    cfg.sampling.traces_rate = 1.0;
    cfg.sampling.metrics_rate = 0.0;
    cfg.tracing.sample_rate = 1.0;
    cfg.exporter.logs_backoff_seconds = 0.0;
    cfg.exporter.logs_retries = crate::config::MAX_EXPORTER_RETRIES;
    cfg.exporter.traces_retries = crate::config::MAX_EXPORTER_RETRIES;
    cfg.exporter.metrics_retries = crate::config::MAX_EXPORTER_RETRIES;
    cfg.validate().expect("boundary values must be accepted");
}

/// Retries above the ceiling would be silently ignored by the resilience
/// layer's attempt cap — reject each signal's field, exactly at the boundary,
/// with the same message TypeScript's `requireRetries` produces.
#[test]
fn each_exporter_retries_field_is_rejected_above_the_ceiling() {
    type SetRetries = fn(&mut TelemetryConfig, usize);
    let over = crate::config::MAX_EXPORTER_RETRIES + 1;
    let cases: [(&str, SetRetries); 3] = [
        ("PROVIDE_EXPORTER_LOGS_RETRIES", |cfg, v| {
            cfg.exporter.logs_retries = v;
        }),
        ("PROVIDE_EXPORTER_TRACES_RETRIES", |cfg, v| {
            cfg.exporter.traces_retries = v;
        }),
        ("PROVIDE_EXPORTER_METRICS_RETRIES", |cfg, v| {
            cfg.exporter.metrics_retries = v;
        }),
    ];
    for (field, set) in cases {
        let mut cfg = valid();
        set(&mut cfg, over);
        let err = cfg
            .validate()
            .expect_err("retries above the ceiling must be rejected");
        assert!(
            err.message.contains(field) && err.message.contains("must be at most 100, got 101"),
            "unexpected message for {field}: {}",
            err.message
        );
    }
}
