// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use super::*;
use crate::testing::acquire_test_state_lock;

/// Run *check* with PROVIDE_CONSENT_LEVEL set to *value* (or unset for `None`),
/// restoring whatever the process had before.
fn with_consent_env(value: Option<&str>, check: impl FnOnce()) {
    let previous = std::env::var(CONSENT_LEVEL_ENV_VAR).ok();
    match value {
        Some(value) => std::env::set_var(CONSENT_LEVEL_ENV_VAR, value),
        None => std::env::remove_var(CONSENT_LEVEL_ENV_VAR),
    }
    check();
    match previous {
        Some(value) => std::env::set_var(CONSENT_LEVEL_ENV_VAR, value),
        None => std::env::remove_var(CONSENT_LEVEL_ENV_VAR),
    }
}

#[test]
fn consent_test_log_level_order_covers_critical_and_unknown() {
    assert_eq!(log_level_order(Some("TRACE")), 0);
    assert_eq!(log_level_order(Some("DEBUG")), 1);
    assert_eq!(log_level_order(Some("INFO")), 2);
    assert_eq!(log_level_order(Some("CRITICAL")), 5);
    assert_eq!(log_level_order(Some("FATAL")), 5);
    // Consent now ranks through the one shared table, so an unrecognised level
    // and an absent one land on INFO rather than the old local default of
    // 0/TRACE. Both sit below the WARN and ERROR gates, so no consent decision
    // changes -- asserted directly below.
    assert_eq!(log_level_order(Some("unexpected")), 2);
    assert_eq!(log_level_order(None), 2);
}

#[test]
fn consent_test_should_allow_covers_functional_and_minimal_policies() {
    // Consent is process-global: without the lock this races the env-loader
    // tests below, which also move the level and read it back.
    let _guard = acquire_test_state_lock();
    reset_consent_for_tests();

    set_consent_level(ConsentLevel::Functional);
    assert!(should_allow("metrics", None));
    assert!(!should_allow("context", None));
    assert!(!should_allow("logs", Some("TRACE")));
    assert!(!should_allow("logs", Some("DEBUG")));
    assert!(!should_allow("logs", Some("INFO")));
    assert!(should_allow("logs", Some("WARNING")));
    assert!(should_allow("logs", Some("WARN")));
    assert!(should_allow("logs", Some("ERROR")));
    assert!(should_allow("logs", Some("CRITICAL")));
    // FATAL used to be unrecognised here, so it ranked 0 and was dropped -- the
    // most severe record in the ladder discarded as if it were the least.
    assert!(should_allow("logs", Some("FATAL")));
    // An unrecognised level now ranks INFO rather than the old 0/TRACE. Both
    // sit below this gate, so the decision is unchanged.
    assert!(!should_allow("logs", Some("unexpected")));
    assert!(!should_allow("logs", None));
    assert!(should_allow("traces", None));

    set_consent_level(ConsentLevel::Minimal);
    assert!(!should_allow("metrics", None));
    assert!(!should_allow("logs", Some("TRACE")));
    assert!(!should_allow("logs", Some("WARN")));
    assert!(should_allow("logs", Some("ERROR")));
    assert!(should_allow("logs", Some("CRITICAL")));
    assert!(should_allow("logs", Some("FATAL")));
    assert!(!should_allow("logs", Some("unexpected")));
    assert!(!should_allow("logs", None));
    assert!(!should_allow("context", None));

    set_consent_level(ConsentLevel::None);
    assert!(!should_allow("logs", Some("CRITICAL")));

    set_consent_level(ConsentLevel::Full);
    assert!(should_allow("logs", Some("DEBUG")));
    assert!(should_allow("metrics", None));

    reset_consent_for_tests();
}
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

// ── PROVIDE_CONSENT_LEVEL ───────────────────────────────────────────────────

#[test]
fn consent_test_parse_consent_level_covers_every_spelling() {
    assert_eq!(parse_consent_level("FULL"), Some(ConsentLevel::Full));
    assert_eq!(
        parse_consent_level("FUNCTIONAL"),
        Some(ConsentLevel::Functional)
    );
    assert_eq!(parse_consent_level("MINIMAL"), Some(ConsentLevel::Minimal));
    assert_eq!(parse_consent_level("NONE"), Some(ConsentLevel::None));
    // Trimmed and upper-cased before the match, so an operator's ` none ` and
    // `minimal` both count.
    assert_eq!(parse_consent_level(" none "), Some(ConsentLevel::None));
    assert_eq!(parse_consent_level("minimal"), Some(ConsentLevel::Minimal));
    assert_eq!(parse_consent_level("BOGUS"), None);
    assert_eq!(parse_consent_level(""), None);
}

/// Each recognised value moves the level -- including FULL, which must be able
/// to widen a level narrowed programmatically, or the env would only ever be
/// able to restrict.
#[test]
fn consent_test_load_from_env_applies_each_recognised_level() {
    let _guard = acquire_test_state_lock();
    reset_consent_for_tests();
    let cases = [
        ("FULL", ConsentLevel::Minimal, ConsentLevel::Full),
        ("FUNCTIONAL", ConsentLevel::Full, ConsentLevel::Functional),
        ("MINIMAL", ConsentLevel::Full, ConsentLevel::Minimal),
        ("NONE", ConsentLevel::Full, ConsentLevel::None),
    ];
    for (raw, before, expected) in cases {
        set_consent_level(before);
        with_consent_env(Some(raw), load_consent_from_env);
        assert_eq!(get_consent_level(), expected, "env {raw:?}");
    }
    reset_consent_for_tests();
}

#[test]
fn consent_test_load_from_env_trims_and_upper_cases() {
    let _guard = acquire_test_state_lock();
    reset_consent_for_tests();

    with_consent_env(Some(" none "), load_consent_from_env);
    assert_eq!(get_consent_level(), ConsentLevel::None);

    with_consent_env(Some("minimal"), load_consent_from_env);
    assert_eq!(get_consent_level(), ConsentLevel::Minimal);

    reset_consent_for_tests();
}

/// An unset variable means the operator has no opinion: a level already set in
/// code stays exactly where it was, rather than being reset to FULL.
#[test]
fn consent_test_load_from_env_leaves_level_untouched_when_unset() {
    let _guard = acquire_test_state_lock();
    reset_consent_for_tests();
    set_consent_level(ConsentLevel::Minimal);

    with_consent_env(None, load_consent_from_env);

    assert_eq!(get_consent_level(), ConsentLevel::Minimal);
    reset_consent_for_tests();
}

/// A misspelled value is ignored, not treated as FULL: silently widening a
/// narrowed level on a typo is the one outcome an opt-out must never produce.
#[test]
fn consent_test_load_from_env_ignores_unrecognised_value() {
    let _guard = acquire_test_state_lock();
    reset_consent_for_tests();
    set_consent_level(ConsentLevel::Minimal);

    with_consent_env(Some("BOGUS"), load_consent_from_env);
    assert_eq!(get_consent_level(), ConsentLevel::Minimal);

    with_consent_env(Some(""), load_consent_from_env);
    assert_eq!(get_consent_level(), ConsentLevel::Minimal);

    reset_consent_for_tests();
}
