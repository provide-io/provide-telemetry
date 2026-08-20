// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Transcribes the log_levels section of spec/behavioral_fixtures.yaml.
//!
//! The canonical ladder, the alias table and the unrecognised-token fallback
//! are cross-language contracts, not Rust choices. Rust's own drift was that
//! level_order folded CRITICAL and FATAL onto ERROR, so a CRITICAL threshold
//! admitted ERROR records and the two most severe levels were indistinguishable.

use provide_telemetry::LoggingConfig;
use serde_json::Value;
use std::collections::BTreeMap;
use std::sync::{Mutex, OnceLock};

// configure_logging and drain_events_for_tests both touch process globals, so
// the two emission tests below must not run concurrently. Same pattern as the
// other logger integration tests, which each own a binary-local lock.
static LOGGER_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn logger_lock() -> &'static Mutex<()> {
    LOGGER_LOCK.get_or_init(|| Mutex::new(()))
}
use provide_telemetry::{level_order, parse_level, try_parse_level, LogSeverity};

#[test]
fn canonical_ladder_has_six_members_in_order() {
    let ladder = [
        (LogSeverity::Trace, 0u8, "TRACE"),
        (LogSeverity::Debug, 1, "DEBUG"),
        (LogSeverity::Info, 2, "INFO"),
        (LogSeverity::Warn, 3, "WARN"),
        (LogSeverity::Error, 4, "ERROR"),
        (LogSeverity::Critical, 5, "CRITICAL"),
    ];
    for (severity, order, name) in ladder {
        assert_eq!(severity.order(), order, "order of {name}");
        assert_eq!(severity.name(), name);
    }
}

#[test]
fn parse_vectors() {
    let recognised = [
        ("ERROR", LogSeverity::Error),
        ("error", LogSeverity::Error),
        ("CrItIcAl", LogSeverity::Critical),
        ("  warn  ", LogSeverity::Warn),
        ("warning", LogSeverity::Warn),
        ("WARNING", LogSeverity::Warn),
        ("FATAL", LogSeverity::Critical),
        ("CRITICAL", LogSeverity::Critical),
        ("TRACE", LogSeverity::Trace),
        ("DEBUG", LogSeverity::Debug),
        ("INFO", LogSeverity::Info),
    ];
    for (input, expected) in recognised {
        assert_eq!(try_parse_level(input), Some(expected), "input {input:?}");
        assert_eq!(parse_level(input, LogSeverity::Info), expected);
        assert_eq!(level_order(input), expected.order());
    }

    for input in ["warnn", "warns", "", "   "] {
        assert_eq!(try_parse_level(input), None, "input {input:?}");
        assert_eq!(parse_level(input, LogSeverity::Info), LogSeverity::Info);
        assert_eq!(level_order(input), LogSeverity::Info.order());
    }
}

#[test]
fn the_fallback_applies_only_to_unrecognised_input() {
    assert_eq!(parse_level("warnn", LogSeverity::Error), LogSeverity::Error);
    assert_eq!(parse_level("debug", LogSeverity::Error), LogSeverity::Debug);
}

#[test]
fn ordering() {
    // CRITICAL used to fold onto ERROR here, which is the drift this closes.
    assert!(parse_level("CRITICAL", LogSeverity::Info) > parse_level("ERROR", LogSeverity::Info));
    assert_eq!(
        parse_level("WARNING", LogSeverity::Info),
        parse_level("WARN", LogSeverity::Info)
    );
    assert_eq!(
        parse_level("FATAL", LogSeverity::Info),
        parse_level("CRITICAL", LogSeverity::Info)
    );
    assert!(parse_level("TRACE", LogSeverity::Info) < parse_level("DEBUG", LogSeverity::Info));
}

#[test]
fn severity_is_debug_printable() {
    // Derived Debug is part of the public surface and must stay exercised:
    // cargo llvm-cov counts it as a function like any other.
    assert_eq!(format!("{:?}", LogSeverity::Critical), "Critical");
}

#[test]
fn logger_log_at_collapses_the_adapter_dispatch_chain() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    // TRACE threshold so every rung of the ladder actually emits; the default
    // is INFO, which would silently drop the DEBUG arm.
    provide_telemetry::logger::configure_logging(LoggingConfig {
        level: "TRACE".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    });
    let _ = provide_telemetry::logger::Logger::drain_events_for_tests();
    let log = provide_telemetry::logger::get_logger(Some("adapter"));

    let on_log =
        |level: &str, message: &str| log.log_at(parse_level(level, LogSeverity::Info), message);
    for (level, message) in [
        ("debug", "a"),
        ("warn", "b"),
        ("warning", "c"),
        ("error", "d"),
        ("fatal", "e"),
        ("nonsense", "f"),
    ] {
        on_log(level, message);
    }

    let levels: Vec<String> = provide_telemetry::logger::Logger::drain_events_for_tests()
        .into_iter()
        .map(|e| e.level)
        .collect();
    provide_telemetry::logger::reset_logging_config_for_tests();
    assert_eq!(
        levels,
        ["DEBUG", "WARN", "WARN", "ERROR", "CRITICAL", "INFO"]
    );
}

#[test]
fn logger_log_at_fields_carries_structured_fields() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    provide_telemetry::logger::configure_logging(LoggingConfig {
        level: "TRACE".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    });
    let _ = provide_telemetry::logger::Logger::drain_events_for_tests();

    let mut fields = BTreeMap::new();
    fields.insert("request_id".to_string(), Value::from("abc"));
    provide_telemetry::logger::get_logger(Some("fields")).log_at_fields(
        LogSeverity::Critical,
        "fields.probe",
        &fields,
    );

    let events = provide_telemetry::logger::Logger::drain_events_for_tests();
    provide_telemetry::logger::reset_logging_config_for_tests();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].level, "CRITICAL");
    assert_eq!(
        events[0].context.get("request_id").and_then(Value::as_str),
        Some("abc")
    );
}

#[test]
fn logger_string_door_normalises_the_level_it_publishes() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    provide_telemetry::logger::configure_logging(LoggingConfig {
        level: "TRACE".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    });
    let _ = provide_telemetry::logger::Logger::drain_events_for_tests();
    let log = provide_telemetry::logger::get_logger(Some("strdoor"));

    // The pre-existing string door used to put the caller's own spelling on
    // the record, so it could publish a level no consumer recognises and
    // disagreed with warn() about how to spell rank 3.
    log.log("warning", "a");
    log.log("bogus", "b");
    log.log("FATAL", "c");
    log.warn("d");
    let mut fields = BTreeMap::new();
    fields.insert("k".to_string(), Value::from("v"));
    log.log_fields("critical", "e", &fields);

    let levels: Vec<String> = provide_telemetry::logger::Logger::drain_events_for_tests()
        .into_iter()
        .map(|e| e.level)
        .collect();
    provide_telemetry::logger::reset_logging_config_for_tests();
    assert_eq!(levels, ["WARN", "INFO", "CRITICAL", "WARN", "CRITICAL"]);
}
