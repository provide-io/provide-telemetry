// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Logger processor chain — runs on every LogEvent before emission.
//!
//! Mirrors the Python `processors.py` pipeline:
//! 1. DARS extraction — extract domain/action/resource/status from Event
//! 2. Logger name injection — insert target as logger_name field if absent
//! 3. Harden input — truncate values, strip control chars, limit attr count
//! 4. Error fingerprint — compute stable hash for error-level events
//! 5. PII sanitization — redact/hash sensitive fields via `pii.rs`
//! 6. Schema enforcement — validate event name format when strict mode is on
//!
//! Called from `log_event()` after the event is built and before emission.

use serde_json::Value;

use crate::config::TelemetryConfig;
use crate::fingerprint::compute_error_fingerprint;
use crate::pii::{detect_secret_in_string, sanitize_payload, REDACTED_SENTINEL};
use crate::runtime::get_runtime_config;
use crate::schema::{event_name, get_strict_schema, validate_required_keys};

use super::LogEvent;

/// Run the full processor chain on a LogEvent in place.
///
/// The order matches the Python processor chain (except sampling/consent
/// which run before this point in `log_event()`).
pub(super) fn process_event(event: &mut LogEvent) {
    let cfg = get_runtime_config().or_else(|| TelemetryConfig::from_env().ok());
    let pii_max_depth = cfg.as_ref().map_or(8, |c| c.pii_max_depth);
    let max_attr_value_length = cfg
        .as_ref()
        .map_or(1024, |c| c.security.max_attr_value_length);
    let max_attr_count = cfg.as_ref().map_or(64, |c| c.security.max_attr_count);

    // 1. DARS extraction (only when Event metadata is attached)
    extract_dars_fields(event);

    // 2. Logger name injection — inserts target as logger_name if not already set
    inject_logger_name(event);

    // 3. Harden input
    harden_input(event, max_attr_value_length, max_attr_count);

    // 4. Error fingerprint
    add_error_fingerprint(event);

    // 5. PII sanitization
    sanitize_context(event, pii_max_depth);

    // 6. Schema enforcement (validate event name when strict mode is on)
    // Annotates with _schema_error instead of dropping — cross-language
    // standard: all four languages (Python/TypeScript/Go/Rust) annotate and emit.
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

/// Inject the logger's target name as `logger_name` into the context.
/// Only sets the field when it is absent — caller-provided values are
/// preserved. Matches Python's `inject_logger_name` processor.
fn inject_logger_name(event: &mut LogEvent) {
    if !event.target.is_empty() {
        event
            .context
            .entry("logger_name".to_string())
            .or_insert_with(|| Value::String(event.target.clone()));
    }
}

/// Truncate long string values, strip control characters, and cap the
/// number of context attributes.
fn harden_input(event: &mut LogEvent, max_value_length: usize, max_attr_count: usize) {
    if max_value_length > 0 {
        for value in event.context.values_mut() {
            if let Value::String(s) = value {
                if s.len() > max_value_length {
                    // Find the last char boundary at or before max_value_length
                    // to avoid panicking on multi-byte UTF-8 codepoints.
                    let safe_end = s
                        .char_indices()
                        .map(|(i, _)| i)
                        .take_while(|&i| i <= max_value_length)
                        .last()
                        .unwrap_or(0);
                    s.truncate(safe_end);
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
    // Cap attribute count. Priority keys (service identity, trace context,
    // DARS fields) are preserved; excess is trimmed from the remainder
    // in BTreeMap alphabetical order (deterministic).
    if max_attr_count > 0 && event.context.len() > max_attr_count {
        use std::collections::HashSet;
        const PRIORITY_KEYS: &[&str] = &[
            "service",
            "env",
            "version",
            "trace_id",
            "span_id",
            "session_id",
            "logger_name",
            "domain",
            "action",
            "resource",
            "status",
            "error_fingerprint",
        ];
        let priority_set: HashSet<&str> = PRIORITY_KEYS.iter().copied().collect();

        // Collect priority keys that are actually present — O(n) with HashSet.
        let mut keep: HashSet<String> = event
            .context
            .keys()
            .filter(|k| priority_set.contains(k.as_str()))
            .cloned()
            .collect();

        // Fill remaining slots from non-priority keys (alphabetical — BTreeMap order).
        for key in event.context.keys() {
            if keep.len() >= max_attr_count {
                break;
            }
            if !priority_set.contains(key.as_str()) {
                keep.insert(key.clone());
            }
        }

        // Drop everything not in `keep` — O(n) with HashSet lookup.
        event.context.retain(|k, _| keep.contains(k));
    }
}

/// Compute a stable error fingerprint for ERROR/CRITICAL-level events
/// that carry an `error` or `error_type` key in context. The fingerprint
/// is a 12-char hex SHA256 prefix, stable across minor stack variations.
fn add_error_fingerprint(event: &mut LogEvent) {
    if !matches!(event.level.as_str(), "ERROR" | "CRITICAL" | "FATAL") {
        return;
    }
    // Only add fingerprint when error/exception attributes exist in the
    // context — matching Python/TypeScript/Go semantics. Plain error-level
    // messages without error metadata do not get fingerprinted.
    let error_name = event
        .context
        .get("error")
        .or_else(|| event.context.get("error_type"))
        .or_else(|| event.context.get("exception"))
        .and_then(|v| v.as_str());
    let Some(error_name) = error_name else {
        return;
    };
    let stack = event
        .context
        .get("stack")
        .or_else(|| event.context.get("stacktrace"))
        .and_then(|v| v.as_str());
    let fingerprint = compute_error_fingerprint(error_name, stack);
    event
        .context
        .insert("error_fingerprint".to_string(), Value::String(fingerprint));
}

/// Sanitize PII/secrets in the context map and scrub the free-form message
/// string. Message is checked directly (not via the map-based engine) so
/// `Path: ["*"]` rules can't match a sentinel key. Mirrors Python/Go.
fn sanitize_context(event: &mut LogEvent, max_depth: usize) {
    if detect_secret_in_string(&event.message) {
        event.message = REDACTED_SENTINEL.to_string();
    }
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
/// dot-joined event name. Invalid names get a `_schema_error` context
/// field — the event is always emitted (never dropped), so telemetry
/// is never lost. Cross-language standard: all four languages annotate
/// and emit rather than drop.
fn enforce_schema(event: &mut LogEvent) {
    if let Some(cfg) = get_runtime_config() {
        if let Err(err) = validate_required_keys(&event.context, &cfg.event_schema.required_keys) {
            event
                .context
                .insert("_schema_error".to_string(), Value::String(err.message));
            return;
        }
    }
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
    fn harden_input_truncates_safely_on_multibyte_utf8() {
        let mut event = make_event("INFO", "test");
        // "é" is 2 bytes in UTF-8; a 5-byte limit could land mid-codepoint
        event
            .context
            .insert("multi".to_string(), Value::String("ééééé".to_string()));
        // Must not panic — truncates at a char boundary before max
        harden_input(&mut event, 5, 64);
        let val = event.context["multi"].as_str().unwrap();
        assert!(val.is_char_boundary(val.len()), "must end at char boundary");
        assert!(val.ends_with("..."));
    }

    #[test]
    fn harden_input_strips_control_chars() {
        let mut event = make_event("INFO", "test");
        event.context.insert(
            "dirty".to_string(),
            Value::String("hello\x00world\ttab\n".to_string()),
        );
        harden_input(&mut event, 1024, 64);
        assert_eq!(
            event.context["dirty"].as_str().unwrap(),
            "helloworld\ttab\n"
        );
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
    fn harden_input_preserves_priority_keys_when_over_cap() {
        let mut event = make_event("INFO", "test");
        // Add 10 generic keys over a cap of 4
        for i in 0..10 {
            event
                .context
                .insert(format!("extra_{i:02}"), Value::String("x".to_string()));
        }
        // Add priority keys — must survive even when over cap
        event
            .context
            .insert("trace_id".to_string(), Value::String("tid-abc".to_string()));
        event
            .context
            .insert("service".to_string(), Value::String("svc".to_string()));
        // Cap at 4: 2 priority keys + 2 generic
        harden_input(&mut event, 1024, 4);
        assert_eq!(event.context.len(), 4, "must cap at 4");
        assert!(
            event.context.contains_key("trace_id"),
            "trace_id (priority) must survive capping"
        );
        assert!(
            event.context.contains_key("service"),
            "service (priority) must survive capping"
        );
    }

    #[test]
    fn error_fingerprint_added_when_error_attr_present() {
        let mut event = make_event("ERROR", "something failed");
        event
            .context
            .insert("error".to_string(), Value::String("ValueError".to_string()));
        add_error_fingerprint(&mut event);
        let fp = event
            .context
            .get("error_fingerprint")
            .unwrap()
            .as_str()
            .unwrap();
        assert_eq!(fp.len(), 12, "fingerprint should be 12 hex chars");
        assert!(fp.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn error_fingerprint_not_added_without_error_attr() {
        let mut event = make_event("ERROR", "plain error message");
        // No "error" or "error_type" in context — fingerprint should NOT be added
        add_error_fingerprint(&mut event);
        assert!(
            !event.context.contains_key("error_fingerprint"),
            "fingerprint requires error attrs in context"
        );
    }

    #[test]
    fn error_fingerprint_not_added_for_info_events() {
        let mut event = make_event("INFO", "normal log");
        event
            .context
            .insert("error".to_string(), Value::String("SomeError".to_string()));
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

    #[test]
    fn inject_logger_name_sets_target_as_logger_name() {
        let mut event = make_event("INFO", "auth.login.ok");
        event.target = "myapp.auth".to_string();
        inject_logger_name(&mut event);
        assert_eq!(
            event.context.get("logger_name").and_then(|v| v.as_str()),
            Some("myapp.auth"),
            "target should be injected as logger_name"
        );
    }

    #[test]
    fn inject_logger_name_does_not_overwrite_caller_provided_value() {
        let mut event = make_event("INFO", "auth.login.ok");
        event.target = "myapp.auth".to_string();
        event.context.insert(
            "logger_name".to_string(),
            Value::String("explicit".to_string()),
        );
        inject_logger_name(&mut event);
        assert_eq!(
            event.context.get("logger_name").and_then(|v| v.as_str()),
            Some("explicit"),
            "caller-set logger_name must not be overwritten"
        );
    }

    #[test]
    fn inject_logger_name_skips_empty_target() {
        let mut event = make_event("INFO", "auth.login.ok");
        event.target = String::new();
        inject_logger_name(&mut event);
        assert!(
            !event.context.contains_key("logger_name"),
            "empty target must not inject logger_name"
        );
    }

    #[test]
    fn harden_input_preserves_logger_name_as_priority_key() {
        let mut event = make_event("INFO", "test");
        for i in 0..10 {
            event
                .context
                .insert(format!("extra_{i:02}"), Value::String("x".to_string()));
        }
        event.context.insert(
            "logger_name".to_string(),
            Value::String("my.logger".to_string()),
        );
        // Cap at 3 — logger_name must survive as a priority key
        harden_input(&mut event, 1024, 3);
        assert!(
            event.context.contains_key("logger_name"),
            "logger_name must survive attribute capping as a priority key"
        );
    }
}

#[cfg(test)]
#[path = "processors_message_pii_tests.rs"]
mod message_pii_tests;
