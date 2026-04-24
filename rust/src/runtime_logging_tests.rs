// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Logging hot-reload parity tests for `update_runtime_config`.
//!
//! The Python reference passes `logging=cfg.logging` through `RuntimeOverrides`
//! so log level, format, and module-level thresholds hot-reload without a
//! provider restart. These tests pin the same contract on the Rust crate.
//!
//! Split out of `runtime_tests.rs` so both stay under the 500-LOC ceiling.

use super::*;

#[test]
fn runtime_test_update_runtime_config_hot_reloads_log_level() {
    let _guard = crate::testing::acquire_test_state_lock();
    crate::testing::reset_telemetry_state();
    crate::logger::reset_logging_config_for_tests();

    // Start at INFO (default). Confirm DEBUG is filtered, then hot-reload to
    // DEBUG via update_runtime_config and confirm DEBUG now passes.
    set_active_config(Some(TelemetryConfig::default()));
    crate::logger::configure_logging(crate::config::LoggingConfig {
        level: "INFO".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..crate::config::LoggingConfig::default()
    });
    crate::logger::enable_json_capture_for_tests();

    let logger = crate::logger::get_logger(Some("tests.runtime.hotlevel"));
    logger.debug("debug.before.reload");
    logger.info("info.before.reload");

    let new_logging = crate::config::LoggingConfig {
        level: "DEBUG".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..crate::config::LoggingConfig::default()
    };

    update_runtime_config(RuntimeOverrides {
        logging: Some(new_logging),
        ..RuntimeOverrides::default()
    })
    .expect("update must succeed");

    logger.debug("debug.after.reload");
    logger.info("info.after.reload");

    let output = String::from_utf8(crate::logger::take_json_capture()).expect("utf8");

    crate::logger::reset_logging_config_for_tests();
    crate::logger::Logger::drain_events_for_tests();
    crate::testing::reset_telemetry_state();

    assert!(
        !output.contains("debug.before.reload"),
        "DEBUG must be filtered under INFO default — got: {output}"
    );
    assert!(
        output.contains("info.before.reload"),
        "INFO must pass under INFO default — got: {output}"
    );
    assert!(
        output.contains("debug.after.reload"),
        "DEBUG must pass after hot-reload to DEBUG — got: {output}"
    );
    assert!(
        output.contains("info.after.reload"),
        "INFO must still pass after hot-reload — got: {output}"
    );
}

#[test]
fn runtime_test_update_runtime_config_hot_reloads_log_format_to_json() {
    let _guard = crate::testing::acquire_test_state_lock();
    crate::testing::reset_telemetry_state();
    crate::logger::reset_logging_config_for_tests();

    // Start on console format, then hot-reload to json and confirm the JSON
    // capture picks up subsequent events.
    set_active_config(Some(TelemetryConfig::default()));
    crate::logger::enable_json_capture_for_tests();

    let logger = crate::logger::get_logger(Some("tests.runtime.hotfmt"));
    // Console format is active — nothing should reach JSON_CAPTURE yet.
    logger.info("console.only.event");

    update_runtime_config(RuntimeOverrides {
        logging: Some(crate::config::LoggingConfig {
            level: "INFO".to_string(),
            fmt: "json".to_string(),
            include_timestamp: false,
            ..crate::config::LoggingConfig::default()
        }),
        ..RuntimeOverrides::default()
    })
    .expect("update must succeed");

    logger.info("json.after.reload");

    let output = String::from_utf8(crate::logger::take_json_capture()).expect("utf8");

    crate::logger::reset_logging_config_for_tests();
    crate::logger::Logger::drain_events_for_tests();
    crate::testing::reset_telemetry_state();

    assert!(
        !output.contains("console.only.event"),
        "console-formatted event must not appear in JSON capture — got: {output}"
    );
    assert!(
        output.contains("json.after.reload"),
        "JSON-formatted event must appear after hot-reload — got: {output}"
    );
}

#[test]
fn runtime_test_update_runtime_config_hot_reloads_module_level_override() {
    let _guard = crate::testing::acquire_test_state_lock();
    crate::testing::reset_telemetry_state();
    crate::logger::reset_logging_config_for_tests();

    // Default level INFO, JSON format, no module override — DEBUG on our
    // target must be filtered. Then hot-reload with a module_levels entry
    // pushing that target to DEBUG and confirm DEBUG passes.
    set_active_config(Some(TelemetryConfig::default()));
    crate::logger::configure_logging(crate::config::LoggingConfig {
        level: "INFO".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..crate::config::LoggingConfig::default()
    });
    crate::logger::enable_json_capture_for_tests();

    let logger = crate::logger::get_logger(Some("tests.runtime.hotmodule"));
    logger.debug("debug.before.module.reload");
    logger.info("info.before.module.reload");

    let mut next_logging = crate::config::LoggingConfig {
        level: "INFO".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..crate::config::LoggingConfig::default()
    };
    next_logging
        .module_levels
        .insert("tests.runtime.hotmodule".to_string(), "DEBUG".to_string());

    update_runtime_config(RuntimeOverrides {
        logging: Some(next_logging),
        ..RuntimeOverrides::default()
    })
    .expect("update must succeed");

    logger.debug("debug.after.module.reload");
    logger.info("info.after.module.reload");

    let output = String::from_utf8(crate::logger::take_json_capture()).expect("utf8");

    crate::logger::reset_logging_config_for_tests();
    crate::logger::Logger::drain_events_for_tests();
    crate::testing::reset_telemetry_state();

    assert!(
        !output.contains("debug.before.module.reload"),
        "DEBUG must be filtered before module-level override applies — got: {output}"
    );
    assert!(
        output.contains("info.before.module.reload"),
        "INFO must pass before the reload — got: {output}"
    );
    assert!(
        output.contains("debug.after.module.reload"),
        "DEBUG must pass for the overridden module after reload — got: {output}"
    );
    assert!(
        output.contains("info.after.module.reload"),
        "INFO must still pass after reload — got: {output}"
    );
}
