// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// Mutation tests for consent.rs — cover consent levels and signal handling

use provide_telemetry::{should_allow, get_consent_level, set_consent_level, ConsentLevel};

#[test]
fn test_should_allow_logs() {
    let result = should_allow("logs");
    assert!(result.is_some(), "logs signal should be allowed");
}

#[test]
fn test_should_allow_traces() {
    let result = should_allow("traces");
    assert!(result.is_some(), "traces signal should be allowed");
}

#[test]
fn test_should_allow_metrics() {
    let result = should_allow("metrics");
    assert!(result.is_some(), "metrics signal should be allowed");
}

#[test]
fn test_should_allow_unknown() {
    let result = should_allow("unknown");
    assert!(result.is_none(), "unknown signal should return None");
}

#[test]
fn test_consent_level_default() {
    let level = get_consent_level();
    assert!(!matches!(level, ConsentLevel::None), "should default to non-None consent");
}

#[test]
fn test_set_consent_level_full() {
    set_consent_level(ConsentLevel::Full);
    let level = get_consent_level();
    assert_eq!(level, ConsentLevel::Full);
}

#[test]
fn test_set_consent_level_none() {
    set_consent_level(ConsentLevel::None);
    let level = get_consent_level();
    assert_eq!(level, ConsentLevel::None);
}
