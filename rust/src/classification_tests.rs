use super::*;
use crate::testing::acquire_test_state_lock;

#[test]
fn classification_test_clear_rules_removes_registered_matches() {
    let _guard = acquire_test_state_lock();
    clear_classification_rules();
    register_classification_rule(ClassificationRule::new("email*", DataClass::Pii));
    assert_eq!(classify_key("email_address").as_deref(), Some("PII"));

    clear_classification_rules();

    assert_eq!(classify_key("email_address"), None);
}

#[test]
fn classification_test_glob_question_mark_matches_one_character_only() {
    assert!(match_glob("ab?d", "abcd"));
    assert!(!match_glob("ab?", "ab"));
}

#[test]
fn classification_test_lookup_action_covers_all_labels_and_unknown() {
    let policy = ClassificationPolicy {
        public: "public".to_string(),
        internal: "internal".to_string(),
        pii: "pii".to_string(),
        phi: "phi".to_string(),
        pci: "pci".to_string(),
        secret: "secret".to_string(),
    };

    assert_eq!(policy.lookup_action("PUBLIC"), "public");
    assert_eq!(policy.lookup_action("INTERNAL"), "internal");
    assert_eq!(policy.lookup_action("PII"), "pii");
    assert_eq!(policy.lookup_action("PHI"), "phi");
    assert_eq!(policy.lookup_action("PCI"), "pci");
    assert_eq!(policy.lookup_action("SECRET"), "secret");
    assert_eq!(policy.lookup_action("UNKNOWN"), "pass");
}

#[test]
fn classification_test_glob_exact_prefix_suffix_and_consecutive_stars() {
    assert!(match_glob("token", "token"));
    assert!(!match_glob("token", "tokenized"));

    assert!(match_glob("user*", "user"));
    assert!(match_glob("user*", "user_id"));
    assert!(!match_glob("user*", "account_user"));

    assert!(match_glob("*_id", "user_id"));
    assert!(match_glob("*_id", "nested_user_id"));
    assert!(!match_glob("*_id", "user_name"));

    assert!(match_glob("user**id", "userid"));
    assert!(match_glob("user**id", "user_42id"));
    assert!(!match_glob("user**id", "user_42name"));
}

#[test]
fn classification_test_glob_internal_star_and_literal_mismatch_paths() {
    assert!(match_glob("user*_id", "user_id"));
    assert!(match_glob("user*_id", "user_123_id"));
    assert!(!match_glob("user*_id", "user_id_suffix"));

    assert!(match_glob("a*b*c", "abc"));
    assert!(match_glob("a*b*c", "axbyc"));
    assert!(!match_glob("a*b*c", "axbyd"));
}

#[test]
fn classification_test_register_rules_extends_and_first_match_wins() {
    let _guard = acquire_test_state_lock();
    clear_classification_rules();
    register_classification_rules(vec![
        ClassificationRule::new("email*", DataClass::Pii),
        ClassificationRule::new("email*", DataClass::Phi),
    ]);

    assert_eq!(classify_key("email_address").as_deref(), Some("PII"));

    clear_classification_rules();
}
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
