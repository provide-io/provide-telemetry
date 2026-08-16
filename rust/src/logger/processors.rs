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

use std::collections::BTreeMap;

use serde_json::Value;

use crate::config::TelemetryConfig;
use crate::fingerprint::compute_error_fingerprint;
use crate::harden::{clean_key, cleaned_key_claims_slot, harden_value, HardenLimits};
use crate::pii::{detect_secret_in_string, redact_secret_spans, sanitize_payload, REDACTED_SENTINEL};
use crate::runtime::get_runtime_config;
use crate::schema::{event_name, get_strict_schema, validate_required_keys};

use super::LogEvent;

fn runtime_config_or_env() -> Option<TelemetryConfig> {
    match get_runtime_config() {
        Some(cfg) => Some(cfg),
        None => TelemetryConfig::from_env().ok(),
    }
}

fn first_context_string<'a>(event: &'a LogEvent, keys: &[&str]) -> Option<&'a str> {
    for key in keys {
        if let Some(Value::String(value)) = event.context.get(*key) {
            return Some(value.as_str());
        }
    }
    None
}

fn runtime_schema_error(event: &LogEvent) -> Option<String> {
    let cfg = get_runtime_config()?;
    match validate_required_keys(&event.context, &cfg.event_schema.required_keys) {
        Ok(()) => None,
        Err(err) => Some(err.message),
    }
}

fn is_priority_key(key: &str) -> bool {
    matches!(
        key,
        "service"
            | "env"
            | "version"
            | "trace_id"
            | "span_id"
            | "session_id"
            | "logger_name"
            | "domain"
            | "action"
            | "resource"
            | "status"
            | "error_fingerprint"
    )
}

/// Run the full processor chain on a LogEvent in place.
///
/// The order matches the Python processor chain (except sampling/consent
/// which run before this point in `log_event()`).
pub(super) fn process_event(event: &mut LogEvent) {
    let cfg = runtime_config_or_env();
    let pii_max_depth = cfg.as_ref().map_or(8, |c| c.pii_max_depth);
    let limits = HardenLimits {
        max_value_length: cfg
            .as_ref()
            .map_or(1024, |c| c.security.max_attr_value_length),
        max_attr_count: cfg.as_ref().map_or(64, |c| c.security.max_attr_count),
        max_depth: cfg.as_ref().map_or(8, |c| c.security.max_nesting_depth),
    };

    // 1. DARS extraction (only when Event metadata is attached)
    extract_dars_fields(event);

    // 2. Logger name injection — inserts target as logger_name if not already set
    inject_logger_name(event);

    // 3. Harden input
    harden_input(event, limits);

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
    let meta = match event.event_metadata.as_ref() {
        Some(meta) => meta,
        None => return,
    };
    event
        .context
        .insert("domain".to_string(), Value::String(meta.domain.clone()));
    event
        .context
        .insert("action".to_string(), Value::String(meta.action.clone()));
    if let Some(resource) = meta.resource.as_ref() {
        event
            .context
            .insert("resource".to_string(), Value::String(resource.clone()));
    }
    event
        .context
        .insert("status".to_string(), Value::String(meta.status.clone()));
}

/// Inject the logger's target name as `logger_name` into the context.
/// Only sets the field when it is absent — caller-provided values are
/// preserved. Matches Python's `inject_logger_name` processor.
fn inject_logger_name(event: &mut LogEvent) {
    if event.target.is_empty() {
        return;
    }
    if event.context.contains_key("logger_name") {
        return;
    }
    event.context.insert(
        "logger_name".to_string(),
        Value::String(event.target.clone()),
    );
}

/// Bound every context value, then cap how many of them survive.
///
/// The values are hardened recursively — depth, width and length at every
/// level — so nothing downstream (PII traversal, receipt canonicalization,
/// renderers, the OTel bridge) has to defend itself against an unbounded
/// structure. The top-level key cap is separate from the one inside
/// [`harden_value`] because it is not a plain first-N: dropping `trace_id` or
/// `service` to make room for a caller's forty-first keyword argument would
/// cost more than it saves.
fn harden_input(event: &mut LogEvent, limits: HardenLimits) {
    for value in event.context.values_mut() {
        // Depth 1: the context map itself is the depth-0 composite.
        *value = harden_value(value, limits, 1);
    }
    cap_attr_count(event, limits.max_attr_count);
    // Top-level keys are hardened as well as values, after the cap — the same
    // order as Python's `harden_input`. [`harden_value`] cleans the keys of
    // *nested* maps, but the context map's own keys — the ones the pretty
    // renderer emits bare as `key=value` — never pass through it, so a key
    // containing "\n2026-08-10 [error] ..." would forge a second,
    // attacker-controlled log line. Mirrors Python's `_harden_keys`.
    harden_keys(&mut event.context);
}

/// Rebuild the context under cleaned keys, resolving collisions safely.
///
/// Cleaning is many-to-one, and the collision policy
/// ([`cleaned_key_claims_slot`]) is what keeps a forged `"trace_i\x00d"`
/// payload key from replacing the genuine `trace_id` and correlating the
/// record to an attacker-chosen trace.
fn harden_keys(context: &mut BTreeMap<String, Value>) {
    use std::collections::BTreeSet;
    let original = std::mem::take(context);
    let mut verbatim: BTreeSet<String> = BTreeSet::new();
    for (key, value) in original {
        let name = clean_key(&key);
        let untouched = name == key;
        if !cleaned_key_claims_slot(
            context.contains_key(&name),
            untouched,
            verbatim.contains(&name),
        ) {
            continue;
        }
        context.insert(name.clone(), value);
        if untouched {
            verbatim.insert(name);
        }
    }
}

/// Cap how many top-level keys survive, keeping priority fields first.
fn cap_attr_count(event: &mut LogEvent, max_attr_count: usize) {
    if max_attr_count == 0 {
        return;
    }
    if event.context.len() <= max_attr_count {
        return;
    }

    use std::collections::BTreeSet;
    let mut keep = BTreeSet::new();
    let priority_keys: Vec<String> = event.context.keys().cloned().collect();
    for key in &priority_keys {
        if is_priority_key(key) {
            keep.insert(key.clone());
        }
    }

    let candidate_keys: Vec<String> = event.context.keys().cloned().collect();
    for key in &candidate_keys {
        if keep.len() >= max_attr_count {
            break;
        }
        if is_priority_key(key) {
            continue;
        }
        keep.insert(key.clone());
    }
    let original_context = std::mem::take(&mut event.context);
    let mut retained = BTreeMap::new();
    for (key, value) in original_context {
        if keep.contains(&key) {
            retained.insert(key, value);
        }
    }
    event.context = retained;
}

/// Compute a stable error fingerprint for ERROR/CRITICAL-level events
/// that carry an `error` or `error_type` key in context. The fingerprint
/// is a 12-char hex SHA256 prefix, stable across minor stack variations.
fn add_error_fingerprint(event: &mut LogEvent) {
    const ERROR_LEVELS: &[&str] = &["ERROR", "CRITICAL", "FATAL"];
    if !ERROR_LEVELS.contains(&event.level.as_str()) {
        return;
    }
    let error_name = first_context_string(event, &["error", "error_type", "exception"]);
    // Only add fingerprint when error/exception attributes exist in the
    // context — matching Python/TypeScript/Go semantics. Plain error-level
    // messages without error metadata do not get fingerprinted.
    let error_name = match error_name {
        Some(error_name) => error_name,
        None => return,
    };
    let stack = first_context_string(event, &["stack", "stacktrace"]);
    let fingerprint = compute_error_fingerprint(error_name, stack);
    event
        .context
        .insert("error_fingerprint".to_string(), Value::String(fingerprint));
}

/// Sanitize PII/secrets in the context map and scrub the free-form message
/// string. Message is checked directly (not via the map-based engine) so
/// `Path: ["*"]` rules can't match a sentinel key. Mirrors Python/Go.
fn sanitize_context(event: &mut LogEvent, max_depth: usize) {
    let message_has_secret = detect_secret_in_string(&event.message);
    if message_has_secret {
        event.message = redact_secret_spans(&event.message);
    }
    if event.context.is_empty() {
        return;
    }
    let payload = Value::Object(event.context.clone().into_iter().collect());
    let cleaned = sanitize_payload(&payload, true, max_depth);
    let object = cleaned
        .as_object()
        .expect("sanitize_payload preserves object shape")
        .clone();
    event.context = object.into_iter().collect();
}

/// When strict schema mode is on, validate the event message as a
/// dot-joined event name. Invalid names get a `_schema_error` context
/// field — the event is always emitted (never dropped), so telemetry
/// is never lost. Cross-language standard: all four languages annotate
/// and emit rather than drop.
fn enforce_schema(event: &mut LogEvent) {
    if let Some(message) = runtime_schema_error(event) {
        event
            .context
            .insert("_schema_error".to_string(), Value::String(message));
        return;
    }
    if !get_strict_schema() {
        return;
    }
    let segments: Vec<&str> = event.message.split('.').collect();
    match event_name(&segments) {
        Ok(_) => {}
        Err(_) => {
            event.context.insert(
                "_schema_error".to_string(),
                Value::String(format!(
                    "event name {:?} does not match strict schema",
                    event.message
                )),
            );
        }
    }
}

#[cfg(test)]
#[path = "processors_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "processors_message_pii_tests.rs"]
mod message_pii_tests;

#[cfg(test)]
#[path = "processors_edge_tests.rs"]
mod edge_tests;

#[cfg(test)]
#[path = "processors_key_hardening_tests.rs"]
mod key_hardening_tests;
