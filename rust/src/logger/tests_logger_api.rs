// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

use super::*;

#[test]
fn wrapper_loggers_cover_public_methods_and_buffering() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    configure_logging(trace_json_config());
    enable_test_capture();

    assert_eq!(logger.target(), "provide.telemetry");
    let test_logger = get_logger(Some("tests.named"));
    assert_eq!(test_logger.target(), "tests.named");

    let mut fields = BTreeMap::new();
    fields.insert("key".to_string(), json!("value"));
    let ev = event(&["orders", "create", "ok"]).expect("event should build");

    test_logger.debug("debug.message");
    test_logger.info("info.message");
    test_logger.warn("warn.message");
    test_logger.error("error.message");
    test_logger.log("TRACE", "trace.message");
    test_logger.debug_fields("debug.fields", &fields);
    test_logger.info_fields("info.fields", &fields);
    test_logger.warn_fields("warn.fields", &fields);
    test_logger.error_fields("error.fields", &fields);
    test_logger.debug_event(&ev);
    test_logger.info_event(&ev);
    test_logger.warn_event(&ev);
    test_logger.error_event(&ev);

    let drained = Logger::drain_events_for_tests();
    assert_eq!(drained.len(), 13);
    assert_eq!(drained[0].target, "tests.named");
    assert_eq!(drained[0].level, "DEBUG");
    assert_eq!(drained[4].level, "TRACE");
    assert_eq!(drained[5].context.get("key"), Some(&json!("value")));
    assert_eq!(
        drained[12]
            .event_metadata
            .as_ref()
            .map(|m| m.status.as_str()),
        Some("ok")
    );

    let null = null_logger(Some("tests.null"));
    assert_eq!(null.target(), "tests.null");
    null.debug("ignored");
    null.info("ignored");
    null.warn("ignored");
    null.error("ignored");
    assert!(Logger::drain_events_for_tests().is_empty());

    let buffered = buffer_logger(Some("tests.buffer"));
    assert_eq!(buffered.target(), "tests.buffer");
    buffered.debug("buffer.debug");
    buffered.info("buffer.info");
    buffered.warn("buffer.warn");
    buffered.error("buffer.error");
    buffered.log("TRACE", "buffer.trace");
    let buffered_events = buffered.drain();
    assert_eq!(buffered_events.len(), 5);
    assert_eq!(buffered_events[0].target, "tests.buffer");
    assert_eq!(buffered_events[4].level, "TRACE");
}

#[test]
fn buffer_logger_respects_threshold_and_global_log_trait_covers_enabled_and_flush() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    configure_logging(crate::config::LoggingConfig {
        level: "WARN".to_string(),
        ..trace_json_config()
    });
    enable_test_capture();

    let buffered = BufferLogger::new(Some("tests.threshold"));
    buffered.debug("filtered.debug");
    buffered.info("filtered.info");
    buffered.warn("kept.warn");
    buffered.error("kept.error");
    let buffered_events = buffered.drain();
    assert_eq!(buffered_events.len(), 2);
    assert_eq!(buffered_events[0].level, "WARN");
    assert_eq!(buffered_events[1].level, "ERROR");

    let facade = Logger::new(Some("tests.trait"));
    let debug_meta = log::Metadata::builder()
        .level(log::Level::Debug)
        .target("tests.trait")
        .build();
    let error_meta = log::Metadata::builder()
        .level(log::Level::Error)
        .target("tests.trait")
        .build();
    assert!(!log::Log::enabled(&facade, &debug_meta));
    assert!(log::Log::enabled(&facade, &error_meta));

    configure_logging(trace_json_config());
    enable_test_capture();
    let trace_record = log::Record::builder()
        .args(format_args!("trace.record"))
        .level(log::Level::Trace)
        .target("tests.trait")
        .build();
    let warn_record = log::Record::builder()
        .args(format_args!("warn.record"))
        .level(log::Level::Warn)
        .target("tests.trait")
        .build();
    log::Log::log(&facade, &trace_record);
    log::Log::log(&facade, &warn_record);
    log::Log::flush(&facade);

    let events = Logger::drain_events_for_tests();
    assert_eq!(events.len(), 2);
    assert_eq!(events[0].level, "TRACE");
    assert_eq!(events[1].level, "WARN");
}

#[test]
fn emit_event_caps_the_fallback_event_buffer() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    configure_logging(trace_json_config());
    enable_test_capture();

    for idx in 0..(MAX_FALLBACK_EVENTS + 2) {
        emit_event(LogEvent {
            level: "INFO".to_string(),
            target: "tests.cap".to_string(),
            message: format!("cap.{idx}"),
            context: BTreeMap::new(),
            trace_id: None,
            span_id: None,
            event_metadata: None,
        });
    }

    let events = Logger::drain_events_for_tests();
    assert_eq!(events.len(), MAX_FALLBACK_EVENTS);
    assert_eq!(
        events.first().map(|event| event.message.as_str()),
        Some("cap.0")
    );
    assert_eq!(
        events.last().map(|event| event.message.as_str()),
        Some("cap.999")
    );
}

#[test]
fn log_fields_with_empty_map_still_emits() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    configure_logging(trace_json_config());
    enable_test_capture();

    let empty_fields_logger = Logger::new(Some("tests.empty.fields"));
    let fields = BTreeMap::new();
    empty_fields_logger.log_fields("INFO", "empty.fields", &fields);

    let events = Logger::drain_events_for_tests();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].message, "empty.fields");
}

#[test]
fn set_as_global_logger_covers_success_and_already_installed_error() {
    let _guard = acquire_test_state_lock();

    assert!(set_as_global_logger().is_ok());
    assert!(set_as_global_logger().is_err());
}
