// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Logger processor chain — runs on every LogEvent before emission.
//!
//! Mirrors the Python `processors.py` pipeline:
//! 1. DARS extraction — extract domain/action/resource/status from Event
//! 2. Harden input — truncate values, strip control chars, limit attr count
//! 3. Error fingerprint — compute stable hash for error-level events
//! 4. PII sanitization — redact/hash sensitive fields via `pii.rs`
//! 5. Schema enforcement — validate event name format when strict mode is on
//!
//! Called from `log_event()` after the event is built and before emission.

use serde_json::Value;

use crate::fingerprint::compute_error_fingerprint;
use crate::pii::sanitize_payload;
use crate::runtime::get_runtime_config;
use crate::schema::{event_name, get_strict_schema};

use super::LogEvent;

/// Run the full processor chain on a LogEvent in place.
///
/// The order matches the Python processor chain (except sampling/consent
/// which run before this point in `log_event()`).
pub(super) fn process_event(event: &mut LogEvent) {
    let cfg = get_runtime_config();
    let pii_max_depth = cfg.as_ref().map_or(8, |c| c.pii_max_depth);
    let max_attr_value_length = cfg.as_ref().map_or(1024, |c| c.security.max_attr_value_length);
    let max_attr_count = cfg.as_ref().map_or(64, |c| c.security.max_attr_count);

    // 1. DARS extraction (only when Event metadata is attached)
    extract_dars_fields(event);

    // 2. Harden input
    harden_input(event, max_attr_value_length, max_attr_count);

    // 3. Error fingerprint
    add_error_fingerprint(event);

    // 4. PII sanitization
    sanitize_context(event, pii_max_depth);

    // 5. Schema enforcement (validate event name when strict mode is on)
    enforce_schema(event);
}

/// Extract DARS (Domain.Action.Resource.Status) fields from an attached
/// Event into the context map. Only fires when `event.event_metadata` is
/// populated (i.e., the caller used `Logger::info_event(&event)` rather
/// than `Logger::info("message")`).
fn extract_dars_fields(event: &mut LogEvent) {
    if let Some(ref meta) = event.event_metadata {
        event
            .context
            .insert("domain".to_string(), Value::String(meta.domain.clone()));
        event
            .context
            .insert("action".to_string(), Value::String(meta.action.clone()));
        if let Some(ref resource) = meta.resource {
            event
                .context
                .insert("resource".to_string(), Value::String(resource.clone()));
        }
        event
            .context
            .insert("status".to_string(), Value::String(meta.status.clone()));
    }
}

/// Truncate long string values, strip control characters, and cap the
/// number of context attributes.
fn harden_input(event: &mut LogEvent, max_value_length: usize, max_attr_count: usize) {
    if max_value_length > 0 {
        for value in event.context.values_mut() {
            if let Value::String(s) = value {
                if s.len() > max_value_length {
                    s.truncate(max_value_length);
                    s.push_str("...");
                }
            }
        }
    }
    // Strip control characters (except newline/tab) from string values.
    for value in event.context.values_mut() {
        if let Value::String(s) = value {
            let cleaned: String = s
                .chars()
                .filter(|c| !c.is_control() || *c == '\n' || *c == '\t')
                .collect();
            if cleaned.len() != s.len() {
                *s = cleaned;
            }
        }
    }
    // Cap attribute count — keep the first N in sorted order (BTreeMap is
    // already sorted, so this preserves alphabetical priority).
    if max_attr_count > 0 && event.context.len() > max_attr_count {
        let keys: Vec<String> = event.context.keys().skip(max_attr_count).cloned().collect();
        for key in keys {
            event.context.remove(&key);
        }
    }
}

/// Compute a stable error fingerprint for ERROR/CRITICAL-level events
/// that carry an `error` or `error_type` key in context. The fingerprint
/// is a 12-char hex SHA256 prefix, stable across minor stack variations.
fn add_error_fingerprint(event: &mut LogEvent) {
    if !matches!(event.level.as_str(), "ERROR" | "CRITICAL" | "FATAL") {
        return;
    }
    let error_name = event
        .context
        .get("error")
        .or_else(|| event.context.get("error_type"))
        .and_then(|v| v.as_str())
        .unwrap_or(&event.message);
    let stack = event
        .context
        .get("stack")
        .or_else(|| event.context.get("stacktrace"))
        .and_then(|v| v.as_str());
    let fingerprint = compute_error_fingerprint(error_name, stack);
    event.context.insert(
        "error_fingerprint".to_string(),
        Value::String(fingerprint),
    );
}

/// Sanitize PII/secrets in the context map using the PII rule engine.
fn sanitize_context(event: &mut LogEvent, max_depth: usize) {
    if event.context.is_empty() {
        return;
    }
    let payload = Value::Object(
        event
            .context
            .iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect(),
    );
    let cleaned = sanitize_payload(&payload, true, max_depth);
    if let Value::Object(map) = cleaned {
        event.context.clear();
        for (k, v) in map {
            event.context.insert(k, v);
        }
    }
}

/// When strict schema mode is on, validate the event message as a
/// dot-joined event name. Invalid names get an `_schema_error` context
/// field (we do NOT drop the event — that would lose telemetry).
fn enforce_schema(event: &mut LogEvent) {
    if !get_strict_schema() {
        return;
    }
    let segments: Vec<&str> = event.message.split('.').collect();
    if event_name(&segments).is_err() {
        event.context.insert(
            "_schema_error".to_string(),
            Value::String(format!(
                "event name {:?} does not match strict schema",
                event.message
            )),
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    fn make_event(level: &str, message: &str) -> LogEvent {
        LogEvent {
            level: level.to_string(),
            target: "test".to_string(),
            message: message.to_string(),
            context: BTreeMap::new(),
            trace_id: None,
            span_id: None,
            event_metadata: None,
        }
    }

    #[test]
    fn harden_input_truncates_long_values() {
        let mut event = make_event("INFO", "test");
        event
            .context
            .insert("long".to_string(), Value::String("x".repeat(2000)));
        harden_input(&mut event, 100, 64);
        let val = event.context["long"].as_str().unwrap();
        assert!(val.len() <= 103, "value should be truncated + '...'");
        assert!(val.ends_with("..."));
    }

    #[test]
    fn harden_input_strips_control_chars() {
        let mut event = make_event("INFO", "test");
        event
            .context
            .insert("dirty".to_string(), Value::String("hello\x00world\ttab\n".to_string()));
        harden_input(&mut event, 1024, 64);
        assert_eq!(event.context["dirty"].as_str().unwrap(), "helloworld\ttab\n");
    }

    #[test]
    fn harden_input_caps_attr_count() {
        let mut event = make_event("INFO", "test");
        for i in 0..20 {
            event
                .context
                .insert(format!("key_{i:02}"), Value::String(format!("val_{i}")));
        }
        harden_input(&mut event, 1024, 5);
        assert_eq!(event.context.len(), 5, "should cap at 5 attributes");
    }

    #[test]
    fn error_fingerprint_added_for_error_events() {
        let mut event = make_event("ERROR", "something failed");
        event
            .context
            .insert("error".to_string(), Value::String("ValueError".to_string()));
        add_error_fingerprint(&mut event);
        let fp = event.context.get("error_fingerprint").unwrap().as_str().unwrap();
        assert_eq!(fp.len(), 12, "fingerprint should be 12 hex chars");
        assert!(fp.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn error_fingerprint_not_added_for_info_events() {
        let mut event = make_event("INFO", "normal log");
        add_error_fingerprint(&mut event);
        assert!(!event.context.contains_key("error_fingerprint"));
    }

    #[test]
    fn sanitize_context_redacts_sensitive_keys() {
        let mut event = make_event("INFO", "test");
        event
            .context
            .insert("password".to_string(), Value::String("s3cret".to_string()));
        event
            .context
            .insert("safe_key".to_string(), Value::String("visible".to_string()));
        sanitize_context(&mut event, 8);
        assert_ne!(
            event.context["password"].as_str().unwrap(),
            "s3cret",
            "password should be redacted"
        );
        assert_eq!(event.context["safe_key"].as_str().unwrap(), "visible");
    }

    #[test]
    fn enforce_schema_adds_error_field_for_invalid_name_in_strict_mode() {
        crate::schema::set_strict_schema(true);
        let mut event = make_event("INFO", "NOT-VALID.name");
        enforce_schema(&mut event);
        assert!(
            event.context.contains_key("_schema_error"),
            "strict mode should flag invalid name"
        );
        crate::schema::set_strict_schema(false);
    }

    #[test]
    fn enforce_schema_passes_valid_name_in_strict_mode() {
        crate::schema::set_strict_schema(true);
        let mut event = make_event("INFO", "auth.login.ok");
        enforce_schema(&mut event);
        assert!(
            !event.context.contains_key("_schema_error"),
            "valid name should not be flagged"
        );
        crate::schema::set_strict_schema(false);
    }
}
