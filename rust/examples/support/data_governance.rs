// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::sync::Arc;

use provide_telemetry::{
    clear_classification_rules, enable_receipts, register_classification_rules, register_pii_rule,
    replace_pii_rules, reset_consent_for_tests, reset_receipts_for_tests, sanitize_payload,
    set_consent_level, should_allow, ClassificationRule, ConsentLevel, DataClass, PIIMode, PIIRule,
    ReceiptOptions, TelemetryError, TestReceiptCollector,
};
use serde_json::json;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DemoSummary {
    pub full_logs_debug_allowed: bool,
    pub none_traces_allowed: bool,
    pub redacted_ssn: Option<String>,
    pub hashed_card_len: Option<usize>,
    pub diagnosis_dropped: bool,
    pub api_key_dropped: bool,
    pub ssn_class: Option<String>,
    pub card_class: Option<String>,
    pub receipt_action: Option<String>,
    pub receipt_hmac_prefix_len: usize,
}

pub fn run_demo() -> Result<DemoSummary, TelemetryError> {
    reset_consent_for_tests();
    clear_classification_rules();
    replace_pii_rules(Vec::new());
    reset_receipts_for_tests();

    set_consent_level(ConsentLevel::Full);
    let full_logs_debug_allowed = should_allow("logs", Some("DEBUG"));
    set_consent_level(ConsentLevel::None);
    let none_traces_allowed = should_allow("traces", None);
    set_consent_level(ConsentLevel::Full);

    register_classification_rules(vec![
        ClassificationRule::new("ssn", DataClass::Pii),
        ClassificationRule::new("card_number", DataClass::Pci),
        ClassificationRule::new("diagnosis", DataClass::Phi),
        ClassificationRule::new("api_*", DataClass::Secret),
    ]);
    register_pii_rule(PIIRule::new(vec!["ssn".into()], PIIMode::Redact, 0));
    register_pii_rule(PIIRule::new(vec!["card_number".into()], PIIMode::Hash, 0));
    register_pii_rule(PIIRule::new(vec!["diagnosis".into()], PIIMode::Drop, 0));
    register_pii_rule(PIIRule::new(vec!["api_key".into()], PIIMode::Drop, 0));

    let cleaned = sanitize_payload(
        &json!({
            "user": "alice",
            "ssn": "123-45-6789",
            "card_number": "4111111111111111",
            "diagnosis": "hypertension",
            "api_key": "sk-prod-abc123", // pragma: allowlist secret
        }),
        true,
        32,
    );

    // Receipts are only worth generating if something takes delivery of them,
    // so the sink comes first and enabling without one is an error.
    let collector = Arc::new(TestReceiptCollector::new());
    enable_receipts(ReceiptOptions {
        enabled: true,
        signing_key: Some("demo-hmac-key".to_string()),
        service_name: Some("governance-demo".to_string()),
        sink: Some(collector.clone()),
    })
    .map_err(|err| TelemetryError::new(err.message))?;
    register_pii_rule(PIIRule::new(vec!["password".into()], PIIMode::Redact, 0));
    let _ = sanitize_payload(&json!({"user": "bob", "password": "s3cr3t"}), true, 32);
    enable_receipts(ReceiptOptions::default()).map_err(|err| TelemetryError::new(err.message))?;
    let receipt = collector.receipts().last().cloned();

    Ok(DemoSummary {
        full_logs_debug_allowed,
        none_traces_allowed,
        redacted_ssn: cleaned
            .get("ssn")
            .and_then(|value| value.as_str().map(str::to_string)),
        hashed_card_len: cleaned
            .get("card_number")
            .and_then(|value| value.as_str().map(str::len)),
        diagnosis_dropped: cleaned.get("diagnosis").is_none(),
        api_key_dropped: cleaned.get("api_key").is_none(),
        ssn_class: cleaned
            .get("__ssn__class")
            .and_then(|value| value.as_str().map(str::to_string)),
        card_class: cleaned
            .get("__card_number__class")
            .and_then(|value| value.as_str().map(str::to_string)),
        receipt_action: receipt.as_ref().map(|entry| entry.action.clone()),
        receipt_hmac_prefix_len: receipt
            .as_ref()
            .and_then(|entry| {
                entry
                    .hmac
                    .as_ref()
                    .map(|hmac: &String| hmac[..8.min(hmac.len())].len())
            })
            .unwrap_or(0),
    })
}
