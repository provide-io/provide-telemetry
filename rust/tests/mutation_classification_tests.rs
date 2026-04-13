// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// Mutation-killing tests for classification.rs (governance feature).
// Specifically targets the match_glob() function and classify_key() lookup.

#[cfg(feature = "governance")]
mod classification_mutation {
    use provide_telemetry::{
        clear_classification_rules, classify_key, register_classification_rule, ClassificationRule,
        DataClass,
    };
    use std::sync::{Mutex, OnceLock};

    static CLS_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

    fn cls_lock() -> &'static Mutex<()> {
        CLS_LOCK.get_or_init(|| Mutex::new(()))
    }

    // ── match_glob: trailing wildcard (starts_with branch) ───────────────────

    // Kills: `key.starts_with(prefix)` → `key.ends_with(prefix)`.
    // "email*" matches "email_address" (starts with "email"), but "address_email"
    // starts with "address" not "email" — starts_with is correct, ends_with is not.
    #[test]
    fn glob_trailing_wildcard_matches_prefix() {
        let _guard = cls_lock().lock().expect("cls lock");
        clear_classification_rules();
        register_classification_rule(ClassificationRule::new("email*", DataClass::Pii));
        assert_eq!(
            classify_key("email_address").as_deref(),
            Some("PII"),
            "trailing wildcard must match key that starts with the prefix"
        );
    }

    // Kills: `key.starts_with(prefix)` → `key.ends_with(prefix)` or `true`.
    // "address_email" ends with "email" but does NOT start with "email".
    #[test]
    fn glob_trailing_wildcard_does_not_match_suffix_only() {
        let _guard = cls_lock().lock().expect("cls lock");
        clear_classification_rules();
        register_classification_rule(ClassificationRule::new("email*", DataClass::Pii));
        assert_eq!(
            classify_key("address_email"),
            None,
            "trailing wildcard must not match key that has prefix only as suffix"
        );
    }

    // Kills: `key.starts_with(prefix)` → `!key.starts_with(prefix)`.
    // Exact prefix match at start: key == pattern prefix alone should still match.
    #[test]
    fn glob_trailing_wildcard_matches_exact_prefix() {
        let _guard = cls_lock().lock().expect("cls lock");
        clear_classification_rules();
        register_classification_rule(ClassificationRule::new("user*", DataClass::Internal));
        assert_eq!(
            classify_key("user").as_deref(),
            Some("INTERNAL"),
            "trailing wildcard must match a key that equals the prefix exactly"
        );
        assert_eq!(
            classify_key("user_id").as_deref(),
            Some("INTERNAL"),
            "trailing wildcard must match key with additional chars after prefix"
        );
    }

    // ── match_glob: empty-suffix guard (the `""` check) ─────────────────────

    // Kills: `""` changed to something else — the `split_once('*')` guard would
    // fire for patterns like "a*b" and incorrectly use starts_with("a").
    // If guard is removed: "a*b" matches "anything" because starts_with("a") is true.
    // With correct guard: "a*b" has non-empty suffix, falls through to pattern == key.
    #[test]
    fn glob_non_trailing_wildcard_is_exact_match_only() {
        let _guard = cls_lock().lock().expect("cls lock");
        clear_classification_rules();
        // Pattern contains * but not at the end — should only exact-match the literal string.
        register_classification_rule(ClassificationRule::new("user*_id", DataClass::Pii));
        // The literal string "user*_id" does not equal "user_id", so no match.
        assert_eq!(
            classify_key("user_id"),
            None,
            "mid-pattern wildcard is not supported; must fall back to exact pattern match"
        );
        // The literal string matches only itself.
        assert_eq!(
            classify_key("user*_id").as_deref(),
            Some("PII"),
            "non-trailing wildcard pattern must match the literal pattern string"
        );
    }

    // ── match_glob: exact match branch (pattern == key) ──────────────────────

    // Kills: `pattern == key` → `true` (every no-wildcard pattern matches anything).
    #[test]
    fn exact_pattern_does_not_match_different_key() {
        let _guard = cls_lock().lock().expect("cls lock");
        clear_classification_rules();
        register_classification_rule(ClassificationRule::new("password", DataClass::Secret));
        assert_eq!(
            classify_key("passwords"),
            None,
            "exact pattern must not match a key with extra trailing characters"
        );
        assert_eq!(
            classify_key("my_password"),
            None,
            "exact pattern must not match a key with extra leading characters"
        );
    }

    // Kills: `pattern == key` → `false` (no exact pattern ever matches).
    #[test]
    fn exact_pattern_matches_identical_key() {
        let _guard = cls_lock().lock().expect("cls lock");
        clear_classification_rules();
        register_classification_rule(ClassificationRule::new("ssn", DataClass::Pii));
        assert_eq!(
            classify_key("ssn").as_deref(),
            Some("PII"),
            "exact pattern must match the identical key"
        );
    }

    // ── classify_key: first-match wins ───────────────────────────────────────

    // Kills: `find()` replaced with `last()` or similar.
    #[test]
    fn classify_key_returns_first_matching_rule() {
        let _guard = cls_lock().lock().expect("cls lock");
        clear_classification_rules();
        register_classification_rule(ClassificationRule::new("email*", DataClass::Pii));
        register_classification_rule(ClassificationRule::new("email*", DataClass::Phi));
        assert_eq!(
            classify_key("email_address").as_deref(),
            Some("PII"),
            "first registered matching rule wins"
        );
    }

    // ── DataClass::as_str round-trips ─────────────────────────────────────────

    // Kills: any as_str arm returning wrong label.
    #[test]
    fn data_class_as_str_all_variants() {
        assert_eq!(DataClass::Public.as_str(), "PUBLIC");
        assert_eq!(DataClass::Internal.as_str(), "INTERNAL");
        assert_eq!(DataClass::Pii.as_str(), "PII");
        assert_eq!(DataClass::Phi.as_str(), "PHI");
        assert_eq!(DataClass::Pci.as_str(), "PCI");
        assert_eq!(DataClass::Secret.as_str(), "SECRET"); // pragma: allowlist secret
    }

    // ── classify_key returns None when no rules registered ───────────────────

    // Kills: removing the `None` return when `find()` yields nothing.
    #[test]
    fn classify_key_returns_none_with_no_rules() {
        let _guard = cls_lock().lock().expect("cls lock");
        clear_classification_rules();
        assert_eq!(classify_key("anything"), None);
    }
}
