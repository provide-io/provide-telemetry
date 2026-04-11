// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
#![cfg(feature = "governance")]
//
use serde_json::json;
use std::sync::{Mutex, OnceLock};

use provide_telemetry::{
    enable_receipts, get_emitted_receipts_for_tests, register_classification_rule,
    register_pii_rule, reset_receipts_for_tests, sanitize_payload, set_consent_level, should_allow,
    ClassificationRule, ConsentLevel, DataClass, PIIMode, PIIRule,
};

static GOVERNANCE_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn governance_lock() -> &'static Mutex<()> {
    GOVERNANCE_LOCK.get_or_init(|| Mutex::new(()))
}

#[test]
fn governance_test_consent_levels_gate_signals() {
    let _guard = governance_lock().lock().expect("governance lock poisoned");
    set_consent_level(ConsentLevel::None);
    assert!(!should_allow("traces", None));
    assert!(!should_allow("metrics", None));
    assert!(!should_allow("context", None));

    set_consent_level(ConsentLevel::Functional);
    assert!(should_allow("logs", Some("ERROR")));
    assert!(!should_allow("logs", Some("DEBUG")));

    set_consent_level(ConsentLevel::Full);
    assert!(should_allow("logs", Some("DEBUG")));
    assert!(should_allow("traces", None));
}

#[test]
fn governance_test_classification_labels_are_added_to_sanitized_output() {
    let _guard = governance_lock().lock().expect("governance lock poisoned");
    provide_telemetry::clear_classification_rules();
    provide_telemetry::replace_pii_rules(Vec::new());

    register_classification_rule(ClassificationRule::new("ssn", DataClass::Pii));
    register_classification_rule(ClassificationRule::new("card_number", DataClass::Pci));
    register_classification_rule(ClassificationRule::new("diagnosis", DataClass::Phi));

    register_pii_rule(PIIRule::new(vec!["ssn".into()], PIIMode::Redact, 0));
    register_pii_rule(PIIRule::new(vec!["card_number".into()], PIIMode::Hash, 0));
    register_pii_rule(PIIRule::new(vec!["diagnosis".into()], PIIMode::Drop, 0));

    let cleaned = sanitize_payload(
        &json!({
            "ssn": "123-45-6789",
            "card_number": "4111111111111111",
            "diagnosis": "hypertension",
        }),
        true,
        32,
    );

    assert_eq!(cleaned["ssn"], "***");
    assert_eq!(cleaned["__ssn__class"], "PII");
    assert_eq!(cleaned["__card_number__class"], "PCI");
    assert_eq!(cleaned["__diagnosis__class"], "PHI");
    assert!(cleaned.get("diagnosis").is_none());
}

#[test]
fn governance_test_receipts_capture_redactions() {
    let _guard = governance_lock().lock().expect("governance lock poisoned");
    reset_receipts_for_tests();
    provide_telemetry::replace_pii_rules(Vec::new());
    register_pii_rule(PIIRule::new(vec!["password".into()], PIIMode::Redact, 0));

    enable_receipts(true, Some("demo-hmac-key"), Some("governance-test"));
    let _ = sanitize_payload(&json!({"password": "s3cr3t"}), true, 32);
    enable_receipts(false, None, None);

    let receipts = get_emitted_receipts_for_tests();
    let receipt = receipts.last().expect("expected a redaction receipt");
    assert_eq!(receipt.field_path, "password");
    assert_eq!(receipt.action, "redact");
    assert!(!receipt.original_hash.is_empty());
    assert!(receipt
        .hmac
        .as_ref()
        .map(|hmac: &String| !hmac.is_empty())
        .unwrap_or(false));
}
