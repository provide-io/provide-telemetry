// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// Mutation-killing tests for classification.rs (governance feature).
// Specifically targets the match_glob() function and classify_key() lookup.

#[cfg(feature = "governance")]
mod classification_mutation {
    use provide_telemetry::{
        classify_key, clear_classification_rules, register_classification_rule, ClassificationRule,
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

    // ── match_glob: internal wildcard (mid-pattern `*`) ─────────────────────

    // Kills: a matcher that only handles trailing `*` and falls through to
    // exact match for mid-pattern `*`, which would make "user*_id" NOT match
    // "user_id".  The correct fnmatch semantics require `*` anywhere to match
    // any (including empty) run of characters.
    #[test]
    fn glob_internal_wildcard_matches_middle_segment() {
        let _guard = cls_lock().lock().expect("cls lock");
        clear_classification_rules();
        register_classification_rule(ClassificationRule::new("user*_id", DataClass::Pii));
        // "*" in the middle can match zero chars → "user_id" matches.
        assert_eq!(
            classify_key("user_id").as_deref(),
            Some("PII"),
            "mid-pattern wildcard must match with zero chars consumed"
        );
        // "*" can also match one or more chars → "user_123_id" matches.
        assert_eq!(
            classify_key("user_123_id").as_deref(),
            Some("PII"),
            "mid-pattern wildcard must match with non-empty run of chars"
        );
        // Anchoring is still enforced: suffix after * must match literally.
        assert_eq!(
            classify_key("user_id_extra"),
            None,
            "mid-pattern wildcard must not match when suffix does not align"
        );
    }

    // Kills: a matcher that treats `*` as match-all even with no leading prefix.
    #[test]
    fn glob_leading_wildcard_matches_suffix() {
        let _guard = cls_lock().lock().expect("cls lock");
        clear_classification_rules();
        register_classification_rule(ClassificationRule::new("*_id", DataClass::Internal));
        assert_eq!(
            classify_key("user_id").as_deref(),
            Some("INTERNAL"),
            "leading wildcard must match key ending with suffix"
        );
        assert_eq!(
            classify_key("order_123_id").as_deref(),
            Some("INTERNAL"),
            "leading wildcard must match key with arbitrary prefix"
        );
        // A key that doesn't end with "_id" must not match.
        assert_eq!(
            classify_key("user_name"),
            None,
            "leading wildcard must not match key without required suffix"
        );
    }

    // Kills: a matcher that collapses multiple `*` into a single wildcard
    // incorrectly or fails to handle them.
    #[test]
    fn glob_multiple_wildcards_match_complex_patterns() {
        let _guard = cls_lock().lock().expect("cls lock");
        clear_classification_rules();
        register_classification_rule(ClassificationRule::new("user*id*", DataClass::Pii));
        assert_eq!(
            classify_key("user_id").as_deref(),
            Some("PII"),
            "multiple wildcards must match key with both segments present"
        );
        assert_eq!(
            classify_key("user_foo_id_bar").as_deref(),
            Some("PII"),
            "multiple wildcards must match key with extra chars in both positions"
        );
        assert_eq!(
            classify_key("userid").as_deref(),
            Some("PII"),
            "multiple wildcards must match when wildcard spans zero chars"
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
