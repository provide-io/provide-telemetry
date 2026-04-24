// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

//! Tests for module-level logger helpers. Split out of `logger/mod.rs` so the
//! parent stays under the 500-LOC ceiling.

use super::*;
use std::collections::{BTreeMap, HashMap};

use serde_json::json;

use crate::runtime::set_active_config;
use crate::schema::event;
use crate::testing::{acquire_test_state_lock, reset_telemetry_state};
use crate::tracer::set_trace_context;
use crate::TelemetryConfig;
#[cfg(feature = "governance")]
use crate::{reset_consent_for_tests, set_consent_level, ConsentLevel};

fn cfg_with_module_level(module: &str, level: &str) -> crate::config::LoggingConfig {
    let mut module_levels = HashMap::new();
    module_levels.insert(module.to_string(), level.to_string());
    crate::config::LoggingConfig {
        level: "INFO".to_string(),
        module_levels,
        ..crate::config::LoggingConfig::default()
    }
}

fn trace_json_config() -> crate::config::LoggingConfig {
    crate::config::LoggingConfig {
        level: "TRACE".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..crate::config::LoggingConfig::default()
    }
}

fn reset_logger_state() {
    reset_telemetry_state();
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();
    let _ = take_json_capture();
    let _ = take_console_capture();
    for key in [
        "PROVIDE_LOG_LEVEL",
        "PROVIDE_LOG_FORMAT",
        "PROVIDE_LOG_INCLUDE_TIMESTAMP",
        "PROVIDE_LOG_MODULE_LEVELS",
        "PROVIDE_SAMPLING_LOGS_RATE",
    ] {
        std::env::remove_var(key);
    }
    #[cfg(feature = "governance")]
    reset_consent_for_tests();
}

fn enable_test_capture() {
    enable_json_capture_for_tests();
    enable_console_capture_for_tests();
}

#[path = "tests_config.rs"]
mod tests_config;
#[path = "tests_event_flow.rs"]
mod tests_event_flow;
#[path = "tests_logger_api.rs"]
mod tests_logger_api;
