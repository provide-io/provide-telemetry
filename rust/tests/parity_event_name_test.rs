// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

//! Executable evidence for the `event_name_contract` fixtures in
//! `spec/behavioral_fixtures.yaml` — one test per case, in fixture order.
//!
//! Rust ships no `validate_event_name`: the crate exposes `event_name` and the
//! spec's API surface requires nothing more, and the remediation's non-goals
//! forbid widening the public API. The dotted-string cases are therefore
//! asserted through the path a Rust caller actually takes — split on the
//! separator, then `event_name` — which exercises the same contract.

use provide_telemetry::schema::{event, event_name, set_strict_schema};
use provide_telemetry::testing::acquire_test_state_lock;
use std::sync::MutexGuard;

/// The strict-schema flag is process-global and cargo runs these tests on
/// parallel threads, so every case holds the shared state lock for its
/// duration and restores the relaxed default on the way out.
fn relaxed() -> MutexGuard<'static, ()> {
    let guard = acquire_test_state_lock();
    set_strict_schema(false);
    guard
}

fn strict() -> MutexGuard<'static, ()> {
    let guard = acquire_test_state_lock();
    set_strict_schema(true);
    guard
}

/// Stands in for the absent `validate_event_name`.
fn validate_dotted(name: &str) -> Result<String, provide_telemetry::EventSchemaError> {
    let segments: Vec<&str> = name.split('.').collect();
    event_name(&segments)
}

// ── variadic entry point: event_name() ───────────────────────────────────────

#[test]
fn parity_event_name_relaxed_single_segment_ok() {
    let _guard = relaxed();
    assert_eq!(event_name(&["startup"]).unwrap(), "startup");
}

#[test]
fn parity_event_name_relaxed_two_segments_ok() {
    let _guard = relaxed();
    assert_eq!(event_name(&["app", "ready"]).unwrap(), "app.ready");
}

#[test]
fn parity_event_name_relaxed_six_segments_ok() {
    let _guard = relaxed();
    assert_eq!(
        event_name(&["a", "b", "c", "d", "e", "f"]).unwrap(),
        "a.b.c.d.e.f"
    );
}

#[test]
fn parity_event_name_relaxed_grammar_not_enforced() {
    let _guard = relaxed();
    assert_eq!(event_name(&["User", "Login-OK"]).unwrap(), "User.Login-OK");
}

#[test]
fn parity_event_name_relaxed_zero_segments_error() {
    let _guard = relaxed();
    assert!(event_name(&[]).is_err(), "zero segments must fail");
}

#[test]
fn parity_event_name_relaxed_empty_segment_error() {
    let _guard = relaxed();
    assert!(
        event_name(&["user", "", "ok"]).is_err(),
        "an empty segment must fail in relaxed mode"
    );
}

#[test]
fn parity_event_name_strict_three_segments_ok() {
    let _guard = strict();
    assert_eq!(
        event_name(&["user", "login", "ok"]).unwrap(),
        "user.login.ok"
    );
}

#[test]
fn parity_event_name_strict_five_segments_ok() {
    let _guard = strict();
    assert_eq!(event_name(&["a", "b", "c", "d", "e"]).unwrap(), "a.b.c.d.e");
}

#[test]
fn parity_event_name_strict_two_segments_error() {
    let _guard = strict();
    let got = event_name(&["too", "few"]);
    assert!(got.is_err(), "2 segments must fail in strict mode");
}

#[test]
fn parity_event_name_strict_six_segments_error() {
    let _guard = strict();
    let got = event_name(&["a", "b", "c", "d", "e", "f"]);
    assert!(got.is_err(), "6 segments must fail in strict mode");
}

#[test]
fn parity_event_name_strict_grammar_enforced() {
    let _guard = strict();
    let got = event_name(&["user", "Login", "ok"]);
    assert!(got.is_err(), "a grammar violation must fail in strict mode");
}

#[test]
fn parity_event_name_strict_zero_segments_error() {
    let _guard = strict();
    let got = event_name(&[]);
    assert!(got.is_err(), "zero segments must fail in strict mode");
}

// ── dotted-string cases, via split + event_name ──────────────────────────────

#[test]
fn parity_validate_event_name_relaxed_single_segment_ok() {
    let _guard = relaxed();
    assert!(validate_dotted("startup").is_ok());
}

#[test]
fn parity_validate_event_name_relaxed_empty_string_error() {
    let _guard = relaxed();
    // "" splits to one empty segment, never zero segments.
    assert!(validate_dotted("").is_err(), r#""" must fail"#);
}

#[test]
fn parity_validate_event_name_relaxed_interior_empty_segment_error() {
    let _guard = relaxed();
    assert!(validate_dotted("a..b").is_err(), r#""a..b" must fail"#);
}

#[test]
fn parity_validate_event_name_relaxed_grammar_not_enforced() {
    let _guard = relaxed();
    assert!(validate_dotted("User.Login-OK").is_ok());
}

#[test]
fn parity_validate_event_name_strict_grammar_enforced() {
    let _guard = strict();
    let got = validate_dotted("user.Login.ok");
    assert!(got.is_err(), "strict mode must enforce grammar");
}

#[test]
fn parity_validate_event_name_strict_two_segments_error() {
    let _guard = strict();
    let got = validate_dotted("too.few");
    assert!(got.is_err(), "2 segments must fail in strict mode");
}

// ── event() is out of scope and must not move ────────────────────────────────

#[test]
fn parity_event_count_rule_unchanged_by_relaxed_mode() {
    let _guard = relaxed();
    assert!(
        event(&["only", "two"]).is_err(),
        "event() must still require 3 or 4 segments"
    );
    assert!(
        event(&["a", "b", "c", "d", "e"]).is_err(),
        "event() must still reject 5 segments"
    );
}
