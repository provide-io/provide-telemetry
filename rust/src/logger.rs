// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;
use std::sync::{Arc, LazyLock, Mutex, OnceLock};

use serde_json::{json, Value};

use crate::config::TelemetryConfig;
use crate::context::get_context;
use crate::runtime::get_runtime_config;
use crate::tracer::get_trace_context;

const MAX_FALLBACK_EVENTS: usize = 1000;

// ---------------------------------------------------------------------------
// JSON stdout/stderr emit — canonical cross-language output
// ---------------------------------------------------------------------------

/// Optional capture buffer used by tests to intercept JSON log lines instead
/// of writing them to stderr.  None means "write to stderr" (production path).
static JSON_CAPTURE: LazyLock<Mutex<Option<Vec<u8>>>> =
    LazyLock::new(|| Mutex::new(None));

/// Enable in-process capture of JSON log lines (test helper).
/// Call before the code under test; retrieve lines with `take_json_capture()`.
pub fn enable_json_capture_for_tests() {
    *JSON_CAPTURE.lock().expect("json capture lock poisoned") = Some(Vec::new());
}

/// Drain and return captured JSON log lines, then disable capture.
pub fn take_json_capture() -> Vec<u8> {
    JSON_CAPTURE
        .lock()
        .expect("json capture lock poisoned")
        .take()
        .unwrap_or_default()
}

/// Format Unix epoch seconds + milliseconds as ISO 8601 UTC.
///
/// Uses the civil-calendar algorithm from
/// <https://howardhinnant.github.io/date_algorithms.html> so no external crate
/// is needed.
fn now_iso8601() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let d = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
    let ts = d.as_secs();
    let ms = d.subsec_millis();
    // All post-1970 timestamps: ts/86400 >= 0, z >= 719_468, era >= 4.
    let z: i64 = (ts / 86_400) as i64 + 719_468;
    let era: i64 = z / 146_097;
    let doe: i64 = z - era * 146_097;
    let yoe: i64 = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let y: i64 = yoe + era * 400;
    let doy: i64 = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp: i64 = (5 * doy + 2) / 153;
    let day: i64 = doy - (153 * mp + 2) / 5 + 1;
    let month: i64 = if mp < 10 { mp + 3 } else { mp - 9 };
    let year: i64 = if month <= 2 { y + 1 } else { y };
    let sod = ts % 86_400;
    let hour = sod / 3_600;
    let min = (sod % 3_600) / 60;
    let sec = sod % 60;
    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{min:02}:{sec:02}.{ms:03}Z")
}

/// Read the active logging config, falling back to env-var parse when
/// `setup_telemetry()` has not yet been called (mirrors Python's lazy-configure
/// behaviour).
fn active_logging_config() -> crate::config::LoggingConfig {
    get_runtime_config()
        .map(|c| c.logging.clone())
        .unwrap_or_else(|| {
            TelemetryConfig::from_env()
                .map(|c| c.logging)
                .unwrap_or_default()
        })
}

/// Serialise a `LogEvent` to a canonical JSON line and write it to the capture
/// buffer (in tests) or stderr (production).
fn emit_json_log(event: &LogEvent) {
    let mut record = json!({
        "msg": event.message,
        "level": event.level,
    });
    let obj = record.as_object_mut().expect("json object");
    // Service identity from context or fallback
    for (k, v) in &event.context {
        obj.insert(k.clone(), v.clone());
    }
    if let Some(tid) = &event.trace_id {
        obj.insert("trace_id".to_string(), Value::String(tid.clone()));
    }
    if let Some(sid) = &event.span_id {
        obj.insert("span_id".to_string(), Value::String(sid.clone()));
    }
    obj.insert("logger_name".to_string(), Value::String(event.target.clone()));
    let line = serde_json::to_string(obj).unwrap_or_default();
    let mut capture = JSON_CAPTURE.lock().expect("json capture lock poisoned");
    if let Some(buf) = capture.as_mut() {
        buf.extend_from_slice(line.as_bytes());
        buf.push(b'\n');
    } else {
        eprintln!("{line}");
    }
}

/// Serialise a `LogEvent` to JSON including a timestamp field and write to
/// the capture buffer or stderr.
fn emit_json_log_with_timestamp(event: &LogEvent) {
    let mut record = json!({
        "msg": event.message,
        "level": event.level,
        "timestamp": now_iso8601(),
    });
    let obj = record.as_object_mut().expect("json object");
    for (k, v) in &event.context {
        obj.insert(k.clone(), v.clone());
    }
    if let Some(tid) = &event.trace_id {
        obj.insert("trace_id".to_string(), Value::String(tid.clone()));
    }
    if let Some(sid) = &event.span_id {
        obj.insert("span_id".to_string(), Value::String(sid.clone()));
    }
    obj.insert("logger_name".to_string(), Value::String(event.target.clone()));
    let line = serde_json::to_string(obj).unwrap_or_default();
    let mut capture = JSON_CAPTURE.lock().expect("json capture lock poisoned");
    if let Some(buf) = capture.as_mut() {
        buf.extend_from_slice(line.as_bytes());
        buf.push(b'\n');
    } else {
        eprintln!("{line}");
    }
}

/// If `PROVIDE_LOG_FORMAT=json`, emit canonical JSON for this event.
fn emit_if_json(event: &LogEvent) {
    let logging = active_logging_config();
    if logging.fmt.eq_ignore_ascii_case("json") {
        if logging.include_timestamp {
            emit_json_log_with_timestamp(event);
        } else {
            emit_json_log(event);
        }
    }
}

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
        let event = new_event(&self.target, level, message);
        emit_if_json(&event);
        let mut buf = events().lock().expect("logger event lock poisoned");
        if buf.len() < MAX_FALLBACK_EVENTS {
            buf.push(event);
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
