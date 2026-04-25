// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::{BTreeMap, HashMap};

use provide_telemetry::testing::{acquire_test_state_lock, reset_telemetry_state};
use provide_telemetry::{
    buffer_logger, configure_logging, get_logger, null_logger, reset_logging_config_for_tests,
    BufferLogger, Logger, LoggingConfig,
};
use serde_json::json;

fn trace_json_config() -> LoggingConfig {
    LoggingConfig {
        level: "TRACE".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        otlp_headers: HashMap::new(),
        otlp_endpoint: None,
        otlp_protocol: String::new(),
        module_levels: HashMap::new(),
    }
}

#[test]
fn logger_wrapper_surface_test_public_helpers_work_from_integration_crate() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    reset_logging_config_for_tests();
    configure_logging(trace_json_config());

    let logger = get_logger(Some("tests.integration.surface"));
    assert_eq!(logger.target(), "tests.integration.surface");

    let mut fields = BTreeMap::new();
    fields.insert("key".to_string(), json!("value"));
    let event = provide_telemetry::schema::event(&["orders", "create", "ok"]).expect("event");

    logger.debug_fields("debug.fields", &fields);
    logger.warn_fields("warn.fields", &fields);
    logger.debug_event(&event);
    logger.warn_event(&event);

    let drained = Logger::drain_events_for_tests();
    assert_eq!(drained.len(), 4);
    assert_eq!(drained[0].level, "DEBUG");
    assert_eq!(drained[1].level, "WARN");
    assert_eq!(
        drained[2]
            .event_metadata
            .as_ref()
            .map(|m| m.status.as_str()),
        Some("ok")
    );
    assert_eq!(
        drained[3]
            .event_metadata
            .as_ref()
            .map(|m| m.status.as_str()),
        Some("ok")
    );
    assert_eq!(drained[0].context.get("key"), Some(&json!("value")));

    let null = null_logger(Some("tests.integration.null"));
    assert_eq!(null.target(), "tests.integration.null");
    null.debug("ignored");
    null.info("ignored");
    null.warn("ignored");
    null.error("ignored");

    let buffered: BufferLogger = buffer_logger(Some("tests.integration.buffer"));
    assert_eq!(buffered.target(), "tests.integration.buffer");
    buffered.debug("buffer.debug");
    buffered.info("buffer.info");
    buffered.warn("buffer.warn");
    buffered.error("buffer.error");

    let buffered_events = buffered.drain();
    assert_eq!(buffered_events.len(), 4);
    assert_eq!(buffered_events[0].level, "DEBUG");
    assert_eq!(buffered_events[1].level, "INFO");
    assert_eq!(buffered_events[2].level, "WARN");
    assert_eq!(buffered_events[3].level, "ERROR");
}
