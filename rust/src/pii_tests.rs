// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use super::*;
use crate::testing::acquire_test_state_lock;

#[test]
fn pii_test_custom_secret_patterns_match_strings() {
    let _guard = crate::testing::acquire_test_state_lock();
    reset_secret_patterns_for_tests();
    register_secret_pattern(
        "custom-secret",
        Regex::new("ULTRA_CUSTOM_SECRET::ALPHA\\|BETA\\|2026").expect("regex must compile"),
    );

    // Asserted through the redaction path rather than a detection predicate,
    // so the test pins what actually reaches a log.
    assert_eq!(
        redact_if_secret("prefix-ULTRA_CUSTOM_SECRET::ALPHA|BETA|2026-suffix"),
        Some("***".to_string()),
    );
    assert_eq!(
        redact_if_secret("benign descriptive text that is intentionally long enough"),
        None,
    );

    reset_secret_patterns_for_tests();
}

#[test]
fn pii_test_max_depth_one_leaves_nested_values_untouched() {
    let _guard = acquire_test_state_lock();
    replace_pii_rules(Vec::new());

    let payload = serde_json::json!({
        "outer": {
            "password": "secret-value",
            "nested": { "token": "abc123" }
        }
    });

    let result = sanitize_payload(&payload, true, 1);

    assert_eq!(result, payload);

    replace_pii_rules(Vec::new());
}

#[test]
fn pii_test_max_depth_boundary_keeps_array_elements_untouched() {
    let _guard = acquire_test_state_lock();
    replace_pii_rules(Vec::new());

    let payload = serde_json::json!({
        "users": [
            { "password": "secret-one" },
            { "token": "secret-two" }
        ]
    });

    let result = sanitize_payload(&payload, true, 2);

    assert_eq!(result, payload);

    replace_pii_rules(Vec::new());
}
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

// ── Path shape ──────────────────────────────────────────────────────────────

/// A span needs at least PATH_MIN_SEGMENTS slash-separated parts before its
/// shape is even considered, so two segments is not a path however wordy.
#[test]
fn pii_test_a_span_with_too_few_segments_is_not_path_shaped() {
    assert!(!looks_like_path("usr/local"));
}

/// Long wordless segments are base64, not directories.
#[test]
fn pii_test_a_span_of_long_wordless_segments_is_not_path_shaped() {
    assert!(!looks_like_path("ABCDEFGHIJ/1234567890/KLMNOPQRST"));
}

/// Three short lowercase words is the smallest thing that reads as a path.
#[test]
fn pii_test_a_span_of_short_lowercase_words_is_path_shaped() {
    assert!(looks_like_path("usr/local/lib"));
}

/// The wordy-segment test is >=, not >: half the segments being words is
/// enough. A deep path often carries a hash or build id beside the words.
#[test]
fn pii_test_a_path_with_exactly_half_wordy_segments_is_path_shaped() {
    assert!(looks_like_path("usr/local/AB12/CD34"));
}

// ── Span collection and merging ─────────────────────────────────────────────

/// One wordy segment in three is a minority, so the span is not a path. Pins
/// the ratio as a product: `wordy + 2 >= 3` would call this a path while
/// `wordy * 2 >= 3` does not.
#[test]
fn pii_test_a_path_with_one_wordy_segment_in_three_is_not_path_shaped() {
    assert!(!looks_like_path("usr/AB12/CD34"));
}

/// aws_key matches the AKIA prefix and long_hex the trailing run; after
/// widening both cover the whole token. Overlapping spans must coalesce, or
/// the token is replaced once per span and emits "******".
#[test]
fn pii_test_a_token_matched_by_two_patterns_is_redacted_once() {
    let _guard = crate::testing::acquire_test_state_lock();
    reset_secret_patterns_for_tests();
    let token = "AKIAIOSFODNN7EXAMPLE0123456789abcdef0123456789abcdef";

    assert_eq!(redact_if_secret(token), Some("***".to_string()));
    assert_eq!(
        redact_if_secret(&format!("a {token} b")),
        Some("a *** b".to_string())
    );
}

/// Patterns are scanned in a fixed order, so a later pattern can match earlier
/// in the string: long_hex hits at index 0 while aws_key hits further along.
/// The spans therefore arrive out of order and must be sorted before they are
/// merged and replaced.
#[test]
fn pii_test_spans_found_out_of_order_are_all_redacted() {
    let _guard = crate::testing::acquire_test_state_lock();
    reset_secret_patterns_for_tests();
    let hex = "a".repeat(44);
    let aws = "AKIAIOSFODNN7EXAMPLE";

    assert_eq!(
        redact_if_secret(&format!("{hex} {aws}")),
        Some("*** ***".to_string())
    );
}

/// The credential is glued to a prefix, so the match begins mid-token and
/// widening must run left to the token's first byte. Every other case puts the
/// secret at a token boundary, where that walk never moves.
#[test]
fn pii_test_a_credential_glued_to_a_prefix_is_removed_whole() {
    let _guard = crate::testing::acquire_test_state_lock();
    reset_secret_patterns_for_tests();
    let secret = "AKIAIOSFODNN7EXAMPLE";

    assert_eq!(
        redact_if_secret(&format!("abcde{secret} tail")),
        Some("*** tail".to_string())
    );
}
