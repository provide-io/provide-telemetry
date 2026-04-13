// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;
use std::sync::{Arc, LazyLock, Mutex, OnceLock};

use serde_json::Value;

use crate::context::get_context;
use crate::health::increment_emitted;
use crate::pii::sanitize_payload;
use crate::sampling::Signal;
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
    // Sanitize context fields through the PII engine before storing in the event.
    let raw_context = get_context();
    let payload = Value::Object(
        raw_context
            .into_iter()
            .collect::<serde_json::Map<String, Value>>(),
    );
    let sanitized = sanitize_payload(&payload, true, 8);
    let context = match sanitized {
        Value::Object(map) => map.into_iter().collect(),
        _ => BTreeMap::new(),
    };
    LogEvent {
        level: level.to_string(),
        target: target.to_string(),
        message: message.to_string(),
        context,
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
        // Count each emitted log event in health counters.
        increment_emitted(Signal::Logs, 1);
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::context::{bind_context, reset_context_for_tests};
    use crate::testing::acquire_test_state_lock;

    #[test]
    fn logger_test_pii_sanitization_redacts_sensitive_fields() {
        let _guard = acquire_test_state_lock();
        reset_context_for_tests();

        // Bind a sensitive field named "password" to context.
        let _ctx = bind_context([(
            "password".to_string(),
            Value::String("secret123".to_string()),
        )]);

        Logger::drain_events_for_tests(); // Clear any prior events.
        let log = get_logger(None);
        log.info("test message");

        let events = Logger::drain_events_for_tests();
        assert_eq!(events.len(), 1);
        let password_val = events[0]
            .context
            .get("password")
            .expect("password field should be present");
        assert_eq!(
            password_val,
            &Value::String("***".to_string()),
            "password field should be redacted to ***"
        );
    }
}
