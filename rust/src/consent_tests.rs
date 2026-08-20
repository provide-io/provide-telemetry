// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use super::*;

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
