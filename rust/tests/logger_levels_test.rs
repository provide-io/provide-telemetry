// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

//! Logger level-filter and tracer/health-counter tests. Split out of
//! tests/logger_test.rs to keep both files under the 500-LOC ceiling.

use std::sync::{Mutex, OnceLock};

use provide_telemetry::{
    configure_logging, enable_json_capture_for_tests, get_logger, reset_logging_config_for_tests,
    set_as_global_logger, take_json_capture, Logger, LoggingConfig,
};

static LOGGER_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn logger_lock() -> &'static Mutex<()> {
    LOGGER_LOCK.get_or_init(|| Mutex::new(()))
}

#[test]
fn logger_test_log_trait_level_warn_filters_info() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let _ = set_as_global_logger();
    let cfg = LoggingConfig {
        level: "WARN".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    };
    configure_logging(cfg);
    enable_json_capture_for_tests();

    log::info!(target: "tests.warn_lvl", "info.filtered");
    log::warn!(target: "tests.warn_lvl", "warn.passes");
    log::error!(target: "tests.warn_lvl", "error.passes");

    let output = String::from_utf8(take_json_capture()).expect("utf8");
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    assert!(
        !output.contains("info.filtered"),
        "INFO must be filtered at WARN level"
    );
    assert!(
        output.contains("warn.passes"),
        "WARN must pass at WARN level"
    );
    assert!(
        output.contains("error.passes"),
        "ERROR must pass at WARN level"
    );
}

#[test]
fn logger_test_log_trait_level_error_filters_warn() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let _ = set_as_global_logger();
    let cfg = LoggingConfig {
        level: "ERROR".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    };
    configure_logging(cfg);
    enable_json_capture_for_tests();

    log::warn!(target: "tests.error_lvl", "warn.filtered");
    log::error!(target: "tests.error_lvl", "error.passes");

    let output = String::from_utf8(take_json_capture()).expect("utf8");
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    assert!(
        !output.contains("warn.filtered"),
        "WARN must be filtered at ERROR level"
    );
    assert!(
        output.contains("error.passes"),
        "ERROR must pass at ERROR level"
    );
}

#[test]
fn logger_test_log_trait_level_debug_allows_debug() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let _ = set_as_global_logger();
    let cfg = LoggingConfig {
        level: "DEBUG".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    };
    configure_logging(cfg);
    enable_json_capture_for_tests();

    log::debug!(target: "tests.debug_lvl", "debug.passes");
    log::info!(target: "tests.debug_lvl", "info.passes");

    let output = String::from_utf8(take_json_capture()).expect("utf8");
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    assert!(
        output.contains("debug.passes"),
        "DEBUG must pass at DEBUG level"
    );
    assert!(
        output.contains("info.passes"),
        "INFO must pass at DEBUG level"
    );
}

#[test]
fn logger_test_log_trait_level_trace_allows_trace() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let _ = set_as_global_logger();
    let cfg = LoggingConfig {
        level: "TRACE".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    };
    configure_logging(cfg);
    enable_json_capture_for_tests();

    log::trace!(target: "tests.trace_lvl", "trace.passes");
    log::debug!(target: "tests.trace_lvl", "debug.passes");

    let output = String::from_utf8(take_json_capture()).expect("utf8");
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    assert!(
        output.contains("trace.passes"),
        "TRACE must pass at TRACE level"
    );
    assert!(
        output.contains("debug.passes"),
        "DEBUG must pass at TRACE level"
    );
}

#[test]
fn logger_test_log_trait_level_aliases_warning_and_critical() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let _ = set_as_global_logger();

    // WARNING is an alias for WARN.
    let cfg = LoggingConfig {
        level: "WARNING".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    };
    configure_logging(cfg);
    enable_json_capture_for_tests();
    log::info!(target: "tests.alias_lvl", "info.filtered.warning");
    log::warn!(target: "tests.alias_lvl", "warn.passes.warning");
    let out1 = String::from_utf8(take_json_capture()).expect("utf8");
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();
    assert!(
        !out1.contains("info.filtered.warning"),
        "INFO filtered under WARNING alias"
    );
    assert!(
        out1.contains("warn.passes.warning"),
        "WARN passes under WARNING alias"
    );

    // CRITICAL is an alias for ERROR.
    let cfg2 = LoggingConfig {
        level: "CRITICAL".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    };
    configure_logging(cfg2);
    enable_json_capture_for_tests();
    log::warn!(target: "tests.alias_lvl", "warn.filtered.critical");
    log::error!(target: "tests.alias_lvl", "error.passes.critical");
    let out2 = String::from_utf8(take_json_capture()).expect("utf8");
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();
    assert!(
        !out2.contains("warn.filtered.critical"),
        "WARN filtered under CRITICAL alias"
    );
    assert!(
        out2.contains("error.passes.critical"),
        "ERROR passes under CRITICAL alias"
    );
}

#[test]
fn logger_test_emitted_logs_increments_on_log() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    use provide_telemetry::get_health_snapshot;

    let before = get_health_snapshot().emitted_logs;
    let logger = get_logger(Some("tests.health"));
    logger.info("logger.health.test");
    Logger::drain_events_for_tests();
    let after = get_health_snapshot().emitted_logs;
    assert!(
        after > before,
        "emitted_logs should increase after a log call (before={before}, after={after})"
    );
}

#[test]
fn logger_test_sampling_zero_drops_log_and_does_not_increment_emitted() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    use provide_telemetry::{get_health_snapshot, set_sampling_policy, SamplingPolicy, Signal};

    provide_telemetry::sampling::_reset_sampling_for_tests();
    provide_telemetry::health::_reset_health_for_tests();

    set_sampling_policy(
        Signal::Logs,
        SamplingPolicy {
            default_rate: 0.0,
            overrides: Default::default(),
        },
    )
    .expect("policy should set");

    let logger = get_logger(Some("tests.sampling_zero"));
    logger.info("should.be.dropped");
    Logger::drain_events_for_tests();

    let snap = get_health_snapshot();
    assert_eq!(
        snap.emitted_logs, 0,
        "emitted_logs must stay 0 when sampling rate is 0.0"
    );
    assert_eq!(
        snap.dropped_logs, 1,
        "dropped_logs must be 1 when sampling rate is 0.0"
    );

    provide_telemetry::sampling::_reset_sampling_for_tests();
    provide_telemetry::health::_reset_health_for_tests();
}

#[test]
fn logger_test_full_queue_drops_log_and_does_not_increment_emitted() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    use provide_telemetry::{
        get_health_snapshot, release, set_queue_policy, try_acquire, QueuePolicy, Signal,
    };

    provide_telemetry::backpressure::_reset_backpressure_for_tests();
    provide_telemetry::health::_reset_health_for_tests();

    // Fill the log queue completely.
    set_queue_policy(QueuePolicy {
        logs_maxsize: 1,
        traces_maxsize: 64,
        metrics_maxsize: 64,
    });
    let ticket = try_acquire(Signal::Logs).expect("first acquire must succeed");

    let logger = get_logger(Some("tests.backpressure"));
    logger.info("should.be.dropped.by.backpressure");
    Logger::drain_events_for_tests();

    let snap = get_health_snapshot();
    assert_eq!(
        snap.emitted_logs, 0,
        "emitted_logs must stay 0 when queue is full"
    );
    assert_eq!(
        snap.dropped_logs, 1,
        "dropped_logs must be 1 when queue is full"
    );

    release(ticket);
    provide_telemetry::backpressure::_reset_backpressure_for_tests();
    provide_telemetry::health::_reset_health_for_tests();
}

#[test]
fn tracer_test_sampling_zero_drops_span_but_still_calls_callback() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    use provide_telemetry::{
        get_health_snapshot, set_sampling_policy, trace, SamplingPolicy, Signal,
    };

    provide_telemetry::sampling::_reset_sampling_for_tests();
    provide_telemetry::health::_reset_health_for_tests();

    set_sampling_policy(
        Signal::Traces,
        SamplingPolicy {
            default_rate: 0.0,
            overrides: Default::default(),
        },
    )
    .expect("policy should set");

    let mut called = false;
    let result = trace("tests.trace.sampled_out", || {
        called = true;
        99_i32
    });

    assert!(
        called,
        "callback must still execute when sampling drops the span"
    );
    assert_eq!(result, 99, "callback return value must be preserved");
    let snap = get_health_snapshot();
    assert_eq!(
        snap.emitted_traces, 0,
        "emitted_traces must stay 0 when sampling rate is 0.0"
    );
    assert_eq!(
        snap.dropped_traces, 1,
        "dropped_traces must be 1 when sampling rate is 0.0"
    );

    provide_telemetry::sampling::_reset_sampling_for_tests();
    provide_telemetry::health::_reset_health_for_tests();
}

#[test]
fn tracer_test_full_queue_drops_span_but_still_calls_callback() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    use provide_telemetry::{
        get_health_snapshot, release, set_queue_policy, trace, try_acquire, QueuePolicy, Signal,
    };

    provide_telemetry::backpressure::_reset_backpressure_for_tests();
    provide_telemetry::health::_reset_health_for_tests();

    // Fill the trace queue completely.
    set_queue_policy(QueuePolicy {
        logs_maxsize: 64,
        traces_maxsize: 1,
        metrics_maxsize: 64,
    });
    let ticket = try_acquire(Signal::Traces).expect("first acquire must succeed");

    let mut called = false;
    let result = trace("tests.trace.backpressure", || {
        called = true;
        77_i32
    });

    assert!(
        called,
        "callback must still execute when backpressure drops the span"
    );
    assert_eq!(result, 77, "callback return value must be preserved");
    let snap = get_health_snapshot();
    assert_eq!(
        snap.emitted_traces, 0,
        "emitted_traces must stay 0 when queue is full"
    );
    assert_eq!(
        snap.dropped_traces, 1,
        "dropped_traces must be 1 when queue is full"
    );

    release(ticket);
    provide_telemetry::backpressure::_reset_backpressure_for_tests();
    provide_telemetry::health::_reset_health_for_tests();
}

#[test]
#[cfg(feature = "governance")]
fn tracer_test_consent_none_skips_emitted_counter() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    use provide_telemetry::{
        get_health_snapshot, reset_consent_for_tests, set_consent_level, ConsentLevel,
    };

    reset_consent_for_tests();
    set_consent_level(ConsentLevel::None);
    let before = get_health_snapshot().emitted_traces;

    let _ = provide_telemetry::trace("test.span", || 42_i32);

    let after = get_health_snapshot().emitted_traces;
    assert_eq!(
        before, after,
        "emitted_traces should not increase when consent is None (before={before}, after={after})"
    );
    reset_consent_for_tests();
}
