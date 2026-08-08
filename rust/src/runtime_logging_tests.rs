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

/// A nested array is bounded before anything consumes the record.
///
/// The two consumers that matter are the local renderer and the OTel bridge,
/// and both read the same `LogEvent` the processor chain hands them — so
/// asserting on the rendered line and on the buffered event together covers
/// both. The array is deliberately nested past the configured ceiling: before
/// hardening recursed, only top-level strings were bounded, so this structure
/// reached the JSON writer and the exporter at full depth.
#[test]
fn runtime_test_nested_arrays_are_hardened_before_local_capture_and_export() {
    let _guard = crate::testing::acquire_test_state_lock();
    crate::testing::reset_telemetry_state();
    crate::logger::reset_logging_config_for_tests();

    set_active_config(Some(TelemetryConfig {
        security: crate::config::SecurityConfig {
            max_attr_value_length: 1024,
            max_attr_count: 64,
            max_nesting_depth: 2,
        },
        ..TelemetryConfig::default()
    }));
    crate::logger::configure_logging(crate::config::LoggingConfig {
        level: "DEBUG".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..crate::config::LoggingConfig::default()
    });
    crate::logger::enable_json_capture_for_tests();

    let mut fields = std::collections::BTreeMap::new();
    fields.insert(
        "rows".to_string(),
        serde_json::json!([["deep", "deeper"], ["deepest"]]),
    );
    crate::logger::get_logger(Some("tests.runtime.harden")).info_fields("harden.probe", &fields);

    let rendered = String::from_utf8(crate::logger::take_json_capture()).expect("utf8");
    let events = crate::logger::Logger::drain_events_for_tests();

    crate::logger::reset_logging_config_for_tests();
    crate::testing::reset_telemetry_state();

    // Found by message rather than by position: the fallback buffer is process
    // global, so a concurrent suite's event can share it.
    let probe = events
        .iter()
        .find(|event| event.message == "harden.probe")
        .expect("the probe event should have been buffered");
    assert_eq!(
        probe.context.get("rows"),
        Some(&serde_json::json!(["***", "***"])),
        "the inner arrays must be refused before the record is handed on"
    );
    assert!(
        !rendered.contains("deepest"),
        "the rendered line must not carry the unbounded value — got: {rendered}"
    );
}

/// In fallback mode — no live OTel log provider — the provider-baked logging
/// fields are still hot: nothing has baked them anywhere yet, so applying them
/// is safe. The reject path only exists for a live provider (see the
/// live-provider test beside the OTel flush tests), and Python behaves the
/// same way.
#[test]
fn runtime_test_update_runtime_config_applies_otlp_fields_without_a_live_provider() {
    let _guard = crate::testing::acquire_test_state_lock();
    crate::testing::reset_telemetry_state();
    crate::logger::reset_logging_config_for_tests();
    set_active_config(Some(TelemetryConfig::default()));

    let new_logging = crate::config::LoggingConfig {
        otlp_endpoint: Some("http://collector.example:4318/v1/logs".to_string()),
        ..crate::config::LoggingConfig::default()
    };
    let next = update_runtime_config(RuntimeOverrides {
        logging: Some(new_logging),
        ..RuntimeOverrides::default()
    })
    .expect("without a live provider the otlp fields are hot");
    assert_eq!(
        next.logging.otlp_endpoint.as_deref(),
        Some("http://collector.example:4318/v1/logs")
    );

    set_active_config(None);
    crate::logger::reset_logging_config_for_tests();
    crate::testing::reset_telemetry_state();
}
