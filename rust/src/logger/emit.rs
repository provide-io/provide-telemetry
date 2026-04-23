// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Log emission helpers: JSON and console output + test capture buffers.
//!
//! Split out from `logger/mod.rs` to keep each file under the 500-LOC cap.

use std::sync::{LazyLock, Mutex};

use serde_json::{json, Value};

use super::{active_logging_config, LogEvent};

// ---------------------------------------------------------------------------
// Test capture buffers
// ---------------------------------------------------------------------------

static JSON_CAPTURE: LazyLock<Mutex<Option<Vec<u8>>>> = LazyLock::new(|| Mutex::new(None));

pub fn enable_json_capture_for_tests() {
    *JSON_CAPTURE.lock().expect("json capture lock poisoned") = Some(Vec::new());
}

pub fn take_json_capture() -> Vec<u8> {
    JSON_CAPTURE
        .lock()
        .expect("json capture lock poisoned")
        .take()
        .unwrap_or_default()
}

static CONSOLE_CAPTURE: LazyLock<Mutex<Option<Vec<u8>>>> = LazyLock::new(|| Mutex::new(None));

pub fn enable_console_capture_for_tests() {
    *CONSOLE_CAPTURE
        .lock()
        .expect("console capture lock poisoned") = Some(Vec::new());
}

pub fn take_console_capture() -> Vec<u8> {
    CONSOLE_CAPTURE
        .lock()
        .expect("console capture lock poisoned")
        .take()
        .unwrap_or_default()
}

// ---------------------------------------------------------------------------
// Timestamp
// ---------------------------------------------------------------------------

pub(super) fn now_iso8601() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let d = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    iso8601_from_unix_parts(d.as_secs(), d.subsec_millis())
}

fn iso8601_from_unix_parts(ts: u64, ms: u32) -> String {
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

// ---------------------------------------------------------------------------
// JSON emit
// ---------------------------------------------------------------------------

fn emit_json_line(event: &LogEvent, include_timestamp: bool) {
    let mut record = if include_timestamp {
        json!({
            "message": event.message,
            "level": event.level,
            "timestamp": now_iso8601(),
        })
    } else {
        json!({
            "message": event.message,
            "level": event.level,
        })
    };
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
    obj.insert(
        "logger_name".to_string(),
        Value::String(event.target.clone()),
    );
    let line = serde_json::to_string(obj).unwrap_or_default();
    let mut capture = JSON_CAPTURE.lock().expect("json capture lock poisoned");
    if let Some(buf) = capture.as_mut() {
        buf.extend_from_slice(line.as_bytes());
        buf.push(b'\n');
    } else {
        eprintln!("{line}");
    }
}

pub(super) fn emit_if_json(event: &LogEvent) {
    let logging = active_logging_config();
    if logging.fmt.eq_ignore_ascii_case("json") {
        emit_json_line(event, logging.include_timestamp);
    }
}

// ---------------------------------------------------------------------------
// Console emit
// ---------------------------------------------------------------------------

fn format_console_line(event: &LogEvent, include_timestamp: bool) -> String {
    let mut s = String::new();
    if include_timestamp {
        s.push_str(&now_iso8601());
        s.push_str("  ");
    }
    s.push_str(&format!("{:<5}", event.level));
    s.push_str("  ");
    s.push_str(&event.target);
    s.push_str("  ");
    s.push_str(&event.message);
    for (k, v) in &event.context {
        s.push_str(&format!("  {k}={v}"));
    }
    s
}

pub(super) fn emit_if_console(event: &LogEvent) {
    let logging = active_logging_config();
    if !logging.fmt.eq_ignore_ascii_case("json") {
        let line = format_console_line(event, logging.include_timestamp);
        let mut capture = CONSOLE_CAPTURE
            .lock()
            .expect("console capture lock poisoned");
        if let Some(buf) = capture.as_mut() {
            buf.extend_from_slice(line.as_bytes());
            buf.push(b'\n');
        } else {
            eprintln!("{line}");
        }
    }
}

#[cfg(feature = "otel")]
pub(super) fn emit_if_otel(event: &LogEvent) {
    crate::otel::logs::emit_log(event);
}

#[cfg(not(feature = "otel"))]
pub(super) fn emit_if_otel(_event: &LogEvent) {}

#[cfg(test)]
#[path = "emit_tests.rs"]
mod tests;
