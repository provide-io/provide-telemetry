// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use std::sync::{Mutex, OnceLock};

use provide_telemetry::{get_logger, trace, Logger};

static LOGGER_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn logger_lock() -> &'static Mutex<()> {
    LOGGER_LOCK.get_or_init(|| Mutex::new(()))
}

#[test]
fn logger_test_logging_works_without_otel() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let logger = get_logger(Some("tests.logger"));

    logger.info("logger.test.info");
    logger.debug("logger.test.debug");
    logger.error("logger.test.error");

    let events = Logger::drain_events_for_tests();
    assert_eq!(events.len(), 3);
    assert_eq!(events[0].target, "tests.logger");
    assert_eq!(events[0].level, "INFO");
    assert_eq!(events[0].message, "logger.test.info");
    assert_eq!(events[2].level, "ERROR");
}

#[test]
fn logger_test_trace_wrapper_works_without_otel() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");

    let observed = std::sync::Mutex::new((None::<String>, None::<String>));
    let result = trace("tests.trace.wrapper", || {
        let trace_context = provide_telemetry::get_trace_context();
        *observed.lock().expect("observed lock poisoned") = (
            trace_context
                .get("trace_id")
                .and_then(std::clone::Clone::clone),
            trace_context
                .get("span_id")
                .and_then(std::clone::Clone::clone),
        );
        41 + 1
    });
    let trace_context = provide_telemetry::get_trace_context();
    let observed = observed.lock().expect("observed lock poisoned");

    assert_eq!(result, 42);
    assert_eq!(observed.0.as_ref().map(std::string::String::len), Some(32));
    assert_eq!(observed.1.as_ref().map(std::string::String::len), Some(16));
    assert_eq!(trace_context.get("trace_id"), Some(&None));
    assert_eq!(trace_context.get("span_id"), Some(&None));
}
