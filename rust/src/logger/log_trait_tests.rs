use super::*;

use crate::config::LoggingConfig;
use crate::testing::acquire_test_state_lock;

fn reset_log_trait_state() {
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();
}

#[test]
fn log_trait_unit_test_maps_info_and_debug_levels() {
    let _guard = acquire_test_state_lock();
    reset_log_trait_state();
    configure_logging(LoggingConfig {
        level: "DEBUG".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    });

    let info = log::Record::builder()
        .args(format_args!("info.record"))
        .level(log::Level::Info)
        .target("tests.log_trait")
        .build();
    let debug = log::Record::builder()
        .args(format_args!("debug.record"))
        .level(log::Level::Debug)
        .target("tests.log_trait")
        .build();

    log::Log::log(&*logger, &info);
    log::Log::log(&*logger, &debug);

    let events = Logger::drain_events_for_tests();
    assert_eq!(events.len(), 2);
    assert_eq!(events[0].level, "INFO");
    assert_eq!(events[1].level, "DEBUG");
}

#[test]
fn log_trait_unit_test_skips_disabled_records() {
    let _guard = acquire_test_state_lock();
    reset_log_trait_state();
    configure_logging(LoggingConfig {
        level: "ERROR".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    });

    let filtered = log::Record::builder()
        .args(format_args!("filtered.info"))
        .level(log::Level::Info)
        .target("tests.log_trait")
        .build();

    log::Log::log(&*logger, &filtered);

    assert!(Logger::drain_events_for_tests().is_empty());
}
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
