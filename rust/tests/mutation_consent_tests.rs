// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// Mutation tests for consent.rs

use provide_telemetry::{should_allow, get_consent_level, set_consent_level, ConsentLevel};

#[test]
fn test_should_allow_logs() {
    let result = should_allow("logs", None);
    assert!(result);
}

#[test]
fn test_should_allow_traces() {
    let result = should_allow("traces", None);
    assert!(result);
}

#[test]
fn test_should_allow_metrics() {
    let result = should_allow("metrics", None);
    assert!(result);
}

#[test]
fn test_should_allow_with_log_level() {
    let result = should_allow("logs", Some("INFO"));
    assert!(result);
}

#[test]
fn test_consent_level_roundtrip() {
    set_consent_level(ConsentLevel::Full);
    let level = get_consent_level();
    assert_eq!(level, ConsentLevel::Full);

    set_consent_level(ConsentLevel::Minimal);
    let level = get_consent_level();
    assert_eq!(level, ConsentLevel::Minimal);
}
