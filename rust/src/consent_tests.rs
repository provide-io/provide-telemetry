use super::*;

#[test]
fn consent_test_log_level_order_covers_critical_and_unknown() {
    assert_eq!(log_level_order(Some("TRACE")), 0);
    assert_eq!(log_level_order(Some("DEBUG")), 1);
    assert_eq!(log_level_order(Some("INFO")), 2);
    assert_eq!(log_level_order(Some("CRITICAL")), 5);
    assert_eq!(log_level_order(Some("unexpected")), 0);
    assert_eq!(log_level_order(None), 0);
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
    assert!(should_allow("traces", None));

    set_consent_level(ConsentLevel::Minimal);
    assert!(!should_allow("metrics", None));
    assert!(!should_allow("logs", Some("TRACE")));
    assert!(!should_allow("logs", Some("WARN")));
    assert!(should_allow("logs", Some("ERROR")));
    assert!(should_allow("logs", Some("CRITICAL")));
    assert!(!should_allow("context", None));

    set_consent_level(ConsentLevel::None);
    assert!(!should_allow("logs", Some("CRITICAL")));

    set_consent_level(ConsentLevel::Full);
    assert!(should_allow("logs", Some("DEBUG")));
    assert!(should_allow("metrics", None));

    reset_consent_for_tests();
}
