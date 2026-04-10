// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;
use std::sync::{LazyLock, Mutex, OnceLock};

use serde_json::Value;

use crate::context::get_context;
use crate::tracing::get_trace_context;

#[derive(Clone, Debug, PartialEq)]
pub struct LogEvent {
    pub level: String,
    pub target: String,
    pub message: String,
    pub context: BTreeMap<String, Value>,
    pub trace_id: Option<String>,
    pub span_id: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Logger {
    target: String,
}

static EVENTS: OnceLock<Mutex<Vec<LogEvent>>> = OnceLock::new();

fn events() -> &'static Mutex<Vec<LogEvent>> {
    EVENTS.get_or_init(|| Mutex::new(Vec::new()))
}

pub static logger: LazyLock<Logger> = LazyLock::new(|| Logger::new(None));

impl Logger {
    pub fn new(target: Option<&str>) -> Self {
        Self {
            target: target.unwrap_or("provide.telemetry").to_string(),
        }
    }

    pub fn target(&self) -> &str {
        &self.target
    }

    pub fn debug(&self, message: &str) {
        self.log("DEBUG", message);
    }

    pub fn info(&self, message: &str) {
        self.log("INFO", message);
    }

    pub fn warn(&self, message: &str) {
        self.log("WARN", message);
    }

    pub fn error(&self, message: &str) {
        self.log("ERROR", message);
    }

    pub fn log(&self, level: &str, message: &str) {
        let trace = get_trace_context();
        let event = LogEvent {
            level: level.to_string(),
            target: self.target.clone(),
            message: message.to_string(),
            context: get_context(),
            trace_id: trace.get("trace_id").and_then(Clone::clone),
            span_id: trace.get("span_id").and_then(Clone::clone),
        };
        events()
            .lock()
            .expect("logger event lock poisoned")
            .push(event);
    }

    pub fn drain_events_for_tests() -> Vec<LogEvent> {
        std::mem::take(&mut *events().lock().expect("logger event lock poisoned"))
    }
}

pub fn get_logger(name: Option<&str>) -> Logger {
    Logger::new(name)
}
