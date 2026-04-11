// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;
use std::sync::{Arc, LazyLock, Mutex, OnceLock};

use serde_json::Value;

use crate::context::get_context;
use crate::tracer::get_trace_context;

const MAX_FALLBACK_EVENTS: usize = 1000;

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

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NullLogger {
    target: String,
}

#[derive(Clone, Debug)]
pub struct BufferLogger {
    target: String,
    events: Arc<Mutex<Vec<LogEvent>>>,
}

static EVENTS: OnceLock<Mutex<Vec<LogEvent>>> = OnceLock::new();

fn events() -> &'static Mutex<Vec<LogEvent>> {
    EVENTS.get_or_init(|| Mutex::new(Vec::new()))
}

pub static logger: LazyLock<Logger> = LazyLock::new(|| Logger::new(None));

fn new_event(target: &str, level: &str, message: &str) -> LogEvent {
    let trace = get_trace_context();
    LogEvent {
        level: level.to_string(),
        target: target.to_string(),
        message: message.to_string(),
        context: get_context(),
        trace_id: trace.get("trace_id").and_then(Clone::clone),
        span_id: trace.get("span_id").and_then(Clone::clone),
    }
}

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
        // Push to test-capture buffer (preserves drain_events_for_tests API)
        let evt = new_event(&self.target, level, message);
        {
            let mut buf = events().lock().expect("logger event lock poisoned");
            if buf.len() < MAX_FALLBACK_EVENTS {
                buf.push(evt);
            }
        }
        // Emit through the active tracing subscriber.
        // `target:` must be a string literal in tracing macros, so we carry the
        // logger name as a structured "logger" field instead.
        // Level must also be const — use individual macros via match.
        let tgt = self.target.as_str();
        match level {
            "DEBUG" => tracing::debug!(logger = tgt, "{}", message),
            "WARN" => tracing::warn!(logger = tgt, "{}", message),
            "ERROR" => tracing::error!(logger = tgt, "{}", message),
            _ => tracing::info!(logger = tgt, "{}", message),
        }
    }

    pub fn drain_events_for_tests() -> Vec<LogEvent> {
        std::mem::take(&mut *events().lock().expect("logger event lock poisoned"))
    }
}

impl NullLogger {
    pub fn new(target: Option<&str>) -> Self {
        Self {
            target: target.unwrap_or("provide.telemetry").to_string(),
        }
    }

    pub fn target(&self) -> &str {
        &self.target
    }

    pub fn debug(&self, _message: &str) {}

    pub fn info(&self, _message: &str) {}

    pub fn warn(&self, _message: &str) {}

    pub fn error(&self, _message: &str) {}
}

impl BufferLogger {
    pub fn new(target: Option<&str>) -> Self {
        Self {
            target: target.unwrap_or("provide.telemetry").to_string(),
            events: Arc::new(Mutex::new(Vec::new())),
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
        self.events
            .lock()
            .expect("buffer logger event lock poisoned")
            .push(new_event(&self.target, level, message));
    }

    pub fn drain(&self) -> Vec<LogEvent> {
        std::mem::take(
            &mut *self
                .events
                .lock()
                .expect("buffer logger event lock poisoned"),
        )
    }
}

pub fn get_logger(name: Option<&str>) -> Logger {
    Logger::new(name)
}

pub fn null_logger(name: Option<&str>) -> NullLogger {
    NullLogger::new(name)
}

pub fn buffer_logger(name: Option<&str>) -> BufferLogger {
    BufferLogger::new(name)
}
