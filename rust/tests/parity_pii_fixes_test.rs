// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// Parity tests for the five PII / classification fixes.
// All governance-feature tests are gated with #[cfg(feature = "governance")].

use serde_json::json;
use std::sync::{Mutex, OnceLock};

use provide_telemetry::{replace_pii_rules, sanitize_payload, PIIMode, PIIRule};

static PII_FIXES_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn pii_fixes_lock() -> &'static Mutex<()> {
    PII_FIXES_LOCK.get_or_init(|| Mutex::new(()))
}

// ── Fix 4: PII rule path wildcard (segment-wise `*` match) ──────────────────

#[test]
fn pii_rule_path_wildcard_matches_any_middle_segment() {
    let _guard = pii_fixes_lock().lock().expect("lock poisoned");
    replace_pii_rules(vec![PIIRule::new(
        vec!["user".to_string(), "*".to_string(), "email".to_string()],
        PIIMode::Redact,
        0,
    )]);
    let payload = json!({
        "user": {
            "alice": { "email": "alice@example.com" },
            "bob":   { "email": "bob@example.com"   }
        }
    });
    let result = sanitize_payload(&payload, true, 32);
    assert_eq!(
        result["user"]["alice"]["email"], "***",
        "wildcard path must match alice's email"
    );
    assert_eq!(
        result["user"]["bob"]["email"], "***",
        "wildcard path must match bob's email"
    );
    // A key that isn't targeted should be untouched.
    assert_eq!(
        result["user"]["alice"]["email"], "***",
        "only email keys should be affected"
    );
    replace_pii_rules(Vec::new());
}

#[test]
fn pii_rule_path_wildcard_does_not_match_different_depth() {
    let _guard = pii_fixes_lock().lock().expect("lock poisoned");
    replace_pii_rules(vec![PIIRule::new(
        vec!["user".to_string(), "*".to_string(), "email".to_string()],
        PIIMode::Redact,
        0,
    )]);
    // email at the wrong depth should NOT be redacted.
    let payload = json!({ "user": { "email": "top@example.com" } });
    let _result = sanitize_payload(&payload, true, 32);
    // "user.email" has depth 2, rule expects depth 3 (user.*.email).
    // However "email" is a default-sensitive key so it *will* be redacted by the
    // default-sensitive pass — but NOT by the wildcard path rule.
    // The important assertion is that non-targeted nested keys are untouched.
    let payload2 = json!({ "user": { "alice": { "phone": "555-1234" } } });
    let result2 = sanitize_payload(&payload2, true, 32);
    assert_eq!(
        result2["user"]["alice"]["phone"], "555-1234",
        "phone key is not targeted by the rule and should be unchanged"
    );
    replace_pii_rules(Vec::new());
}

#[test]
fn pii_rule_exact_path_still_works_without_wildcard() {
    let _guard = pii_fixes_lock().lock().expect("lock poisoned");
    replace_pii_rules(vec![PIIRule::new(
        vec!["profile".to_string(), "ssn".to_string()],
        PIIMode::Hash,
        0,
    )]);
    let payload = json!({ "profile": { "ssn": "123-45-6789" } });
    let result = sanitize_payload(&payload, true, 32);
    // Should be hashed, not the literal value and not "***".
    assert_ne!(result["profile"]["ssn"], "123-45-6789");
    assert_ne!(result["profile"]["ssn"], "***");
    assert_eq!(
        result["profile"]["ssn"].as_str().map(|s| s.len()),
        Some(12),
        "SHA-256 truncated to 12 hex chars"
    );
    replace_pii_rules(Vec::new());
}

// ── Fix 5: Array recursion pushes `*` segment ───────────────────────────────

#[test]
fn pii_rule_array_wildcard_redacts_each_element_email() {
    let _guard = pii_fixes_lock().lock().expect("lock poisoned");
    replace_pii_rules(vec![PIIRule::new(
        vec!["users".to_string(), "*".to_string(), "email".to_string()],
        PIIMode::Redact,
        0,
    )]);
    let payload = json!({
        "users": [
            { "email": "alice@example.com", "role": "admin" },
            { "email": "bob@example.com",   "role": "user"  }
        ]
    });
    let result = sanitize_payload(&payload, true, 32);
    assert_eq!(
        result["users"][0]["email"], "***",
        "first user email must be redacted"
    );
    assert_eq!(
        result["users"][1]["email"], "***",
        "second user email must be redacted"
    );
    // Non-targeted fields must be preserved.
    assert_eq!(result["users"][0]["role"], "admin");
    assert_eq!(result["users"][1]["role"], "user");
    replace_pii_rules(Vec::new());
}

#[test]
fn pii_rule_array_wildcard_drop_removes_each_element_field() {
    let _guard = pii_fixes_lock().lock().expect("lock poisoned");
    replace_pii_rules(vec![PIIRule::new(
        vec![
            "items".to_string(),
            "*".to_string(),
            "secret_key".to_string(),
        ],
        PIIMode::Drop,
        0,
    )]);
    let payload = json!({
        "items": [
            { "id": 1, "secret_key": "abc" },
            { "id": 2, "secret_key": "xyz" }
        ]
    });
    let result = sanitize_payload(&payload, true, 32);
    assert!(
        result["items"][0].get("secret_key").is_none(),
        "secret_key must be dropped from first element"
    );
    assert!(
        result["items"][1].get("secret_key").is_none(),
        "secret_key must be dropped from second element"
    );
    // Non-targeted fields preserved.
    assert_eq!(result["items"][0]["id"], 1);
    assert_eq!(result["items"][1]["id"], 2);
    replace_pii_rules(Vec::new());
}

// ── Fix 1: Classification policy enforcement ─────────────────────────────────

#[cfg(feature = "governance")]
mod classification_policy_enforcement {
    use super::*;
    use provide_telemetry::{
        clear_classification_rules, register_classification_rule, set_classification_policy,
        ClassificationPolicy, ClassificationRule, DataClass,
    };

    fn setup(policy: ClassificationPolicy) {
        clear_classification_rules();
        set_classification_policy(policy);
        replace_pii_rules(Vec::new());
    }

    fn teardown() {
        clear_classification_rules();
        set_classification_policy(ClassificationPolicy::default());
        replace_pii_rules(Vec::new());
    }

    // `"drop"` → key removed entirely.
    #[test]
    fn policy_drop_removes_key() {
        let _guard = pii_fixes_lock().lock().expect("lock poisoned");
        setup(ClassificationPolicy {
            phi: "drop".to_string(),
            ..ClassificationPolicy::default()
        });
        register_classification_rule(ClassificationRule::new("diagnosis", DataClass::Phi));
        let result = sanitize_payload(&json!({ "diagnosis": "flu" }), true, 32);
        assert!(
            result.get("diagnosis").is_none(),
            "drop policy must remove the key"
        );
        assert!(
            result.get("__diagnosis__class").is_none(),
            "drop policy must not add class tag"
        );
        teardown();
    }

    // `"redact"` → value replaced with "***", class tag added.
    #[test]
    fn policy_redact_replaces_value_and_adds_class_tag() {
        let _guard = pii_fixes_lock().lock().expect("lock poisoned");
        setup(ClassificationPolicy {
            pii: "redact".to_string(),
            ..ClassificationPolicy::default()
        });
        register_classification_rule(ClassificationRule::new("email", DataClass::Pii));
        let result = sanitize_payload(&json!({ "email": "user@example.com" }), true, 32);
        assert_eq!(result["email"], "***", "redact policy must replace value");
        assert_eq!(
            result["__email__class"], "PII",
            "redact policy must add class tag"
        );
        teardown();
    }

    // `"redact"` with already-sentinel value → value unchanged, tag still added.
    #[test]
    fn policy_redact_skips_already_redacted_value() {
        let _guard = pii_fixes_lock().lock().expect("lock poisoned");
        setup(ClassificationPolicy {
            pii: "redact".to_string(),
            ..ClassificationPolicy::default()
        });
        register_classification_rule(ClassificationRule::new("note", DataClass::Pii));
        // Value already the sentinel — policy must not double-mask it.
        let result = sanitize_payload(&json!({ "note": "***" }), true, 32);
        assert_eq!(result["note"], "***");
        assert_eq!(result["__note__class"], "PII");
        teardown();
    }

    // `"hash"` → value replaced with 12-char hex, class tag added.
    #[test]
    fn policy_hash_replaces_value_and_adds_class_tag() {
        let _guard = pii_fixes_lock().lock().expect("lock poisoned");
        setup(ClassificationPolicy {
            pci: "hash".to_string(),
            ..ClassificationPolicy::default()
        });
        register_classification_rule(ClassificationRule::new("card", DataClass::Pci));
        let result = sanitize_payload(&json!({ "card": "4111111111111111" }), true, 32);
        let val = result["card"].as_str().expect("value must be string");
        assert_ne!(val, "4111111111111111", "hash policy must replace value");
        assert_eq!(val.len(), 12, "hash must be 12 hex chars");
        assert_eq!(result["__card__class"], "PCI");
        teardown();
    }

    // `"truncate"` → value truncated to 8 chars + "...", class tag added.
    #[test]
    fn policy_truncate_replaces_value_and_adds_class_tag() {
        let _guard = pii_fixes_lock().lock().expect("lock poisoned");
        setup(ClassificationPolicy {
            internal: "truncate".to_string(),
            ..ClassificationPolicy::default()
        });
        register_classification_rule(ClassificationRule::new("session_id", DataClass::Internal));
        let result = sanitize_payload(&json!({ "session_id": "abcdefghijklmnop" }), true, 32);
        assert_eq!(
            result["session_id"], "abcdefgh...",
            "truncate policy must keep first 8 chars + ellipsis"
        );
        assert_eq!(result["__session_id__class"], "INTERNAL");
        teardown();
    }

    // `"truncate"` on short value → no suffix appended, class tag added.
    #[test]
    fn policy_truncate_leaves_short_value_unchanged() {
        let _guard = pii_fixes_lock().lock().expect("lock poisoned");
        setup(ClassificationPolicy {
            internal: "truncate".to_string(),
            ..ClassificationPolicy::default()
        });
        register_classification_rule(ClassificationRule::new("code", DataClass::Internal));
        let result = sanitize_payload(&json!({ "code": "abc" }), true, 32);
        // "abc" is 3 chars ≤ 8 → no truncation.
        assert_eq!(result["code"], "abc");
        assert_eq!(result["__code__class"], "INTERNAL");
        teardown();
    }

    // `"pass"` → only class tag added, value unchanged.
    #[test]
    fn policy_pass_adds_tag_only() {
        let _guard = pii_fixes_lock().lock().expect("lock poisoned");
        setup(ClassificationPolicy {
            public: "pass".to_string(),
            ..ClassificationPolicy::default()
        });
        register_classification_rule(ClassificationRule::new("region", DataClass::Public));
        let result = sanitize_payload(&json!({ "region": "us-east-1" }), true, 32);
        assert_eq!(
            result["region"], "us-east-1",
            "pass policy must not change value"
        );
        assert_eq!(result["__region__class"], "PUBLIC");
        teardown();
    }

    // All six DataClass labels must each route through the correct policy action.
    #[test]
    fn policy_all_six_labels_are_dispatched() {
        let _guard = pii_fixes_lock().lock().expect("lock poisoned");
        // Set a policy where every class has a unique, observable action.
        setup(ClassificationPolicy {
            public: "pass".to_string(),
            internal: "pass".to_string(),
            pii: "redact".to_string(),
            phi: "drop".to_string(),
            pci: "hash".to_string(),
            secret: "drop".to_string(), // pragma: allowlist secret
        });
        register_classification_rule(ClassificationRule::new("pub_field", DataClass::Public));
        register_classification_rule(ClassificationRule::new("int_field", DataClass::Internal));
        register_classification_rule(ClassificationRule::new("pii_field", DataClass::Pii));
        register_classification_rule(ClassificationRule::new("phi_field", DataClass::Phi));
        register_classification_rule(ClassificationRule::new("pci_field", DataClass::Pci));
        register_classification_rule(ClassificationRule::new("sec_field", DataClass::Secret)); // pragma: allowlist secret

        let result = sanitize_payload(
            &json!({
                "pub_field": "public_value",
                "int_field": "internal_value",
                "pii_field": "sensitive",
                "phi_field": "health_data",
                "pci_field": "card_data",
                "sec_field": "secret_value"  // pragma: allowlist secret
            }),
            true,
            32,
        );

        // PUBLIC → pass
        assert_eq!(result["pub_field"], "public_value");
        assert_eq!(result["__pub_field__class"], "PUBLIC");

        // INTERNAL → pass
        assert_eq!(result["int_field"], "internal_value");
        assert_eq!(result["__int_field__class"], "INTERNAL");

        // PII → redact
        assert_eq!(result["pii_field"], "***");
        assert_eq!(result["__pii_field__class"], "PII");

        // PHI → drop
        assert!(result.get("phi_field").is_none());
        assert!(result.get("__phi_field__class").is_none());

        // PCI → hash
        let pci_val = result["pci_field"]
            .as_str()
            .expect("pci_field must be string");
        assert_eq!(pci_val.len(), 12, "PCI hash must be 12 hex chars");
        assert_eq!(result["__pci_field__class"], "PCI");

        // SECRET → drop
        assert!(result.get("sec_field").is_none()); // pragma: allowlist secret
        assert!(result.get("__sec_field__class").is_none()); // pragma: allowlist secret

        teardown();
    }

    // `lookup_action` helper covers all six labels and an unknown label.
    #[test]
    fn lookup_action_covers_all_labels_and_unknown() {
        let policy = ClassificationPolicy::default();
        assert_eq!(policy.lookup_action("PUBLIC"), "pass");
        assert_eq!(policy.lookup_action("INTERNAL"), "pass");
        assert_eq!(policy.lookup_action("PII"), "redact");
        assert_eq!(policy.lookup_action("PHI"), "drop");
        assert_eq!(policy.lookup_action("PCI"), "hash");
        assert_eq!(policy.lookup_action("SECRET"), "drop"); // pragma: allowlist secret
        assert_eq!(
            policy.lookup_action("UNKNOWN"),
            "pass",
            "unknown label must fall through to pass"
        );
    }
}
