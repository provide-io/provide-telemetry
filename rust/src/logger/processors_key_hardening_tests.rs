// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Tests for top-level context-key hardening (`harden_keys`).
//!
//! The pretty renderer emits keys bare (`key=value`), so a control character
//! in a context key — reachable from a caller's payload — could forge an
//! entire additional log line. These pin the Rust leg of the cross-SDK fix
//! that added `_harden_keys` to Python.

use super::*;
use crate::testing::acquire_test_state_lock;
use std::collections::BTreeMap;

fn limits() -> HardenLimits {
    HardenLimits {
        max_value_length: 1024,
        max_attr_count: 64,
        max_depth: 8,
    }
}

fn event_with_context(context: BTreeMap<String, Value>) -> LogEvent {
    LogEvent {
        level: "INFO".to_string(),
        target: "tests.harden_keys".to_string(),
        message: "payment.recorded".to_string(),
        context,
        trace_id: None,
        span_id: None,
        event_metadata: None,
    }
}

#[test]
fn a_newline_in_a_top_level_key_is_stripped() {
    let mut context = BTreeMap::new();
    context.insert("bad\nkey".to_string(), Value::Bool(true));
    let mut event = event_with_context(context);

    harden_input(&mut event, limits());

    assert_eq!(event.context.get("badkey"), Some(&Value::Bool(true)));
    assert!(!event.context.contains_key("bad\nkey"));
}

/// Keys drop TAB and CR too — the key set is `[\x00-\x1f\x7f]`, wider than
/// the value set, because keys are rendered bare.
#[test]
fn tabs_carriage_returns_and_del_in_keys_are_stripped() {
    let mut context = BTreeMap::new();
    context.insert("ta\tb\rkey\u{7f}".to_string(), Value::from(1));
    let mut event = event_with_context(context);

    harden_input(&mut event, limits());

    assert_eq!(event.context.get("tabkey"), Some(&Value::from(1)));
}

#[test]
fn nested_map_keys_are_cleaned_as_well() {
    let mut context = BTreeMap::new();
    context.insert(
        "outer".to_string(),
        serde_json::json!({ "in\u{1}ner": { "deep\nest": "v" } }),
    );
    let mut event = event_with_context(context);

    harden_input(&mut event, limits());

    assert_eq!(
        event.context.get("outer"),
        Some(&serde_json::json!({ "inner": { "deepest": "v" } }))
    );
}

/// A sanitized key must never displace the genuine field it collides with:
/// `"trace_i\x00d"` cleaning to `"trace_id"` is exactly the vector Python's
/// `_harden_keys` docstring documents.
#[test]
fn a_sanitized_key_never_displaces_a_verbatim_one() {
    let mut context = BTreeMap::new();
    // BTreeMap iterates "trace_i\u{0}d" before "trace_id" (squatter first)...
    context.insert("trace_i\u{0}d".to_string(), Value::String("forged".into()));
    context.insert("trace_id".to_string(), Value::String("real".into()));
    // ...and "zz" before "zz\n" (verbatim first).
    context.insert("zz".to_string(), Value::String("real".into()));
    context.insert("zz\n".to_string(), Value::String("forged".into()));
    let mut event = event_with_context(context);

    harden_input(&mut event, limits());

    assert_eq!(
        event.context.get("trace_id"),
        Some(&Value::String("real".into()))
    );
    assert_eq!(event.context.get("zz"), Some(&Value::String("real".into())));
    assert_eq!(event.context.len(), 2);
}

/// End to end through the processor chain and the pretty renderer: a key
/// carrying a fake timestamp-and-level suffix must not split the rendered
/// output into a second, forged log line.
#[test]
fn a_forged_key_no_longer_splits_the_pretty_output() {
    let _guard = acquire_test_state_lock();
    // Pin the shipping defaults: without an active config `process_event`
    // falls back to `TelemetryConfig::from_env()`, and ambient env vars would
    // make this test's limits depend on what ran before it.
    crate::runtime::set_active_config(Some(crate::config::TelemetryConfig::default()));
    std::env::remove_var("PROVIDE_LOG_PRETTY_FIELDS");

    let mut context = BTreeMap::new();
    context.insert(
        "amount\n2026-08-10 [error] payment.failed amount=9999".to_string(),
        Value::from(1),
    );
    let mut event = event_with_context(context);
    process_event(&mut event);

    let cfg = crate::config::LoggingConfig {
        fmt: "pretty".to_string(),
        include_timestamp: false,
        ..crate::config::LoggingConfig::default()
    };
    let line = super::super::pretty::format_pretty_line_with_colors(&event, &cfg, false);

    assert!(
        !line.contains('\n'),
        "a context key must not forge a second log line: {line:?}"
    );
    assert!(
        line.contains("amount2026-08-10 [error] payment.failed amount=9999=1"),
        "the cleaned key must survive on the single line: {line:?}"
    );

    crate::runtime::set_active_config(None);
}
