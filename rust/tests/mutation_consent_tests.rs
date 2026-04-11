// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// Mutation tests for consent.rs

use std::sync::{Mutex, MutexGuard, OnceLock};

use provide_telemetry::{
    get_consent_level, reset_consent_for_tests, set_consent_level, should_allow, ConsentLevel,
};

static CONSENT_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn consent_lock() -> MutexGuard<'static, ()> {
    CONSENT_LOCK
        .get_or_init(|| Mutex::new(()))
        .lock()
        .expect("consent test lock poisoned")
}

#[test]
fn test_should_allow_with_full_consent() {
    let _g = consent_lock();
    reset_consent_for_tests();
    assert!(should_allow("logs", None));
    assert!(should_allow("traces", None));
    assert!(should_allow("metrics", None));
}

#[test]
fn test_should_allow_with_none_consent() {
    let _g = consent_lock();
    set_consent_level(ConsentLevel::None);
    assert!(!should_allow("logs", None));
    assert!(!should_allow("traces", None));
    assert!(!should_allow("metrics", None));
    reset_consent_for_tests();
}

#[test]
fn test_should_allow_log_level_with_functional_consent() {
    let _g = consent_lock();
    set_consent_level(ConsentLevel::Functional);
    // Functional: logs only at WARNING+ (order >= 3)
    assert!(!should_allow("logs", Some("INFO"))); // INFO = order 2, blocked
    assert!(should_allow("logs", Some("WARNING"))); // WARNING = order 3, allowed
    assert!(should_allow("logs", Some("ERROR"))); // ERROR = order 4, allowed
    reset_consent_for_tests();
}

#[test]
fn test_consent_level_roundtrip() {
    let _g = consent_lock();
    reset_consent_for_tests();
    assert_eq!(get_consent_level(), ConsentLevel::Full);

    set_consent_level(ConsentLevel::Minimal);
    assert_eq!(get_consent_level(), ConsentLevel::Minimal);

    set_consent_level(ConsentLevel::None);
    assert_eq!(get_consent_level(), ConsentLevel::None);

    reset_consent_for_tests();
    assert_eq!(get_consent_level(), ConsentLevel::Full);
}
