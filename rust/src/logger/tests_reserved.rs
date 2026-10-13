// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

//! `reserved_root_fields.replacement_reporting` in spec/telemetry-api.yaml,
//! and the contract case `reserved_root_fields_replacement_reported`.

use super::*;

fn identity_config(version: &str) {
    set_active_config(Some(TelemetryConfig {
        service_name: "svc".to_string(),
        environment: "stage".to_string(),
        version: version.to_string(),
        ..TelemetryConfig::default()
    }));
}

fn fields(pairs: &[(&str, &str)]) -> BTreeMap<String, Value> {
    pairs
        .iter()
        .map(|(k, v)| ((*k).to_string(), json!(v)))
        .collect()
}

fn replacements() -> u64 {
    crate::health::get_health_snapshot().reserved_field_replacements
}

/// The warnings among the buffered events, as the fields they name.
fn warned() -> Vec<String> {
    Logger::drain_events_for_tests()
        .into_iter()
        .filter(|e| e.message == reserved::WARNING_EVENT)
        .map(|e| {
            assert_eq!(e.level, "WARN");
            assert_eq!(e.target, "provide.telemetry.logger");
            e.context["field"].as_str().unwrap().to_string()
        })
        .collect()
}

#[test]
fn a_replaced_field_is_counted_and_warned_about_once() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    identity_config("1.2.3");

    let record = build_event(
        "tests.reserved",
        "INFO",
        "reserved.fields.ok",
        &fields(&[("version", "9.9.9"), ("env", "forged")]),
    );
    assert_eq!(record.context.get("version"), Some(&json!("1.2.3")));
    assert_eq!(warned(), ["env", "version"]);
    assert_eq!(replacements(), 2);

    build_event(
        "tests.reserved",
        "INFO",
        "again",
        &fields(&[("version", "8.8.8")]),
    );
    assert!(warned().is_empty());
    assert_eq!(replacements(), 3);
}

#[test]
fn the_warning_never_carries_the_callers_value() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    identity_config("1.2.3");
    build_event(
        "tests.reserved",
        "INFO",
        "m",
        &fields(&[("version", "secret-7")]),
    );
    let events = Logger::drain_events_for_tests();
    let warning = events
        .iter()
        .find(|e| e.message == reserved::WARNING_EVENT)
        .expect("warning");
    assert!(!format!("{warning:?}").contains("secret-7"));
}

#[test]
fn an_equal_value_and_an_empty_config_value_replace_nothing() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    identity_config("1.2.3");
    build_event(
        "tests.reserved",
        "INFO",
        "m",
        &fields(&[("version", "1.2.3"), ("service", "svc")]),
    );
    identity_config("");
    build_event(
        "tests.reserved",
        "INFO",
        "m",
        &fields(&[("version", "9.9.9")]),
    );
    assert!(warned().is_empty());
    assert_eq!(replacements(), 0);
}

#[test]
fn trace_ids_count_only_while_a_span_is_live() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    identity_config("1.2.3");
    let forged = fields(&[("trace_id", "forged-trace"), ("span_id", "forged-span")]);
    build_event("tests.reserved", "INFO", "m", &forged);
    assert_eq!(replacements(), 0);

    let _trace = set_trace_context(
        Some("0123456789abcdef0123456789abcdef".to_string()), // pragma: allowlist secret
        Some("0123456789abcdef".to_string()),                 // pragma: allowlist secret
    );
    build_event("tests.reserved", "INFO", "m", &forged);
    assert_eq!(warned(), ["trace_id", "span_id"]);
    assert_eq!(replacements(), 2);
}

#[test]
fn a_bound_value_counts_once_and_not_for_its_own_warning() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    identity_config("1.2.3");
    let _bound = crate::context::bind_context([("version", json!("bound"))]);
    build_event("tests.reserved", "INFO", "m", &BTreeMap::new());
    assert_eq!(warned(), ["version"]);
    // The warning is built with the same bound context; it is not a second
    // replacement the caller made.
    assert_eq!(replacements(), 1);
}

#[test]
fn a_non_string_caller_value_differs_from_the_stamped_string() {
    let mut context = BTreeMap::new();
    context.insert("version".to_string(), json!(2));
    assert!(reserved::replaces(&context, "version", "2"));
    assert!(!reserved::replaces(&context, "env", "prod"));
}

#[test]
fn the_reset_forgets_which_fields_were_warned_about() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    identity_config("1.2.3");
    build_event(
        "tests.reserved",
        "INFO",
        "m",
        &fields(&[("version", "9.9.9")]),
    );
    assert_eq!(warned(), ["version"]);
    reset_reserved_warnings_for_tests();
    build_event(
        "tests.reserved",
        "INFO",
        "m",
        &fields(&[("version", "9.9.9")]),
    );
    assert_eq!(warned(), ["version"]);
}
