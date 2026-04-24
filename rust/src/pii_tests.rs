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

    assert!(detect_secret_in_string(
        "prefix-ULTRA_CUSTOM_SECRET::ALPHA|BETA|2026-suffix"
    ));
    assert!(!detect_secret_in_string(
        "benign descriptive text that is intentionally long enough"
    ));

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
