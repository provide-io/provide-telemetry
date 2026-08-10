// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use super::*;

use serde_json::json;

const LIMITS: HardenLimits = HardenLimits {
    max_value_length: 8,
    max_attr_count: 2,
    max_depth: 3,
};

#[test]
fn harden_test_scalars_pass_through_unchanged() {
    for value in [json!(null), json!(true), json!(7), json!(1.5)] {
        assert_eq!(harden_value(&value, LIMITS, 0), value);
    }
}

#[test]
fn harden_test_strings_are_truncated_then_stripped_at_every_level() {
    let hardened = harden_value(
        &json!({ "a": { "b": "line\u{0}break-and-more" } }),
        LIMITS,
        0,
    );

    // Truncated to 8 bytes ("line\0bre") and marked, then the NUL is dropped.
    assert_eq!(hardened, json!({ "a": { "b": "linebre..." } }));
}

/// Truncation cuts on a character boundary, never mid-codepoint — otherwise a
/// multi-byte value would produce a `String` that cannot exist.
#[test]
fn harden_test_truncation_respects_character_boundaries() {
    let limits = HardenLimits {
        max_value_length: 5,
        ..LIMITS
    };

    assert_eq!(
        harden_value(&json!("héllo wörld"), limits, 0),
        json!("héll...")
    );
}

/// A limit that falls inside a multi-byte character keeps nothing of it: the
/// alternative is a cut that would not be valid UTF-8.
#[test]
fn harden_test_truncation_drops_a_character_it_cannot_fit() {
    let mut value = "\u{e9}\u{e9}".to_string();
    truncate_string_value(&mut value, 1);
    assert_eq!(value, "...");

    let mut value = "a\u{e9}z".to_string();
    truncate_string_value(&mut value, 2);
    assert_eq!(value, "a...");
}

#[test]
fn harden_test_zero_length_limit_disables_truncation() {
    let limits = HardenLimits {
        max_value_length: 0,
        ..LIMITS
    };

    assert_eq!(
        harden_value(&json!("a value far longer than eight bytes"), limits, 0),
        json!("a value far longer than eight bytes")
    );
}

/// The whole reason this stage exists: a structure deeper than the configured
/// ceiling is refused, not passed through for a serializer to deal with.
#[test]
fn harden_test_composites_at_the_depth_ceiling_collapse() {
    let deep = json!({ "l1": { "l2": { "l3": { "l4": "unreachable" } } } });

    assert_eq!(
        harden_value(&deep, LIMITS, 0),
        json!({ "l1": { "l2": { "l3": "***" } } })
    );
}

#[test]
fn harden_test_arrays_are_bounded_by_the_same_ceiling() {
    let nested = json!([[[["deep"]]]]);

    assert_eq!(harden_value(&nested, LIMITS, 0), json!([[["***"]]]));
}

#[test]
fn harden_test_map_width_is_capped_at_every_level() {
    let wide = json!({ "outer": { "a": 1, "b": 2, "c": 3, "d": 4 } });

    assert_eq!(
        harden_value(&wide, LIMITS, 0),
        json!({ "outer": { "a": 1, "b": 2 } })
    );
}

#[test]
fn harden_test_zero_width_cap_means_unlimited() {
    let limits = HardenLimits {
        max_attr_count: 0,
        ..LIMITS
    };
    let wide = json!({ "a": 1, "b": 2, "c": 3, "d": 4 });

    assert_eq!(harden_value(&wide, limits, 0), wide);
}
