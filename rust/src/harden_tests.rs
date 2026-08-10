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
fn harden_test_strings_are_stripped_then_truncated_at_every_level() {
    let hardened = harden_value(
        &json!({ "a": { "b": "line\u{0}break-and-more" } }),
        LIMITS,
        0,
    );

    // The NUL is dropped first, then the cleaned value is cut at 8 bytes and
    // marked — the cap counts characters a reader will actually see.
    assert_eq!(hardened, json!({ "a": { "b": "linebrea..." } }));
}

/// The order is observable, not cosmetic: truncating first lets a
/// control-heavy prefix spend the whole budget, collapsing the value to just
/// the marker. Python/Go/TS strip first; Rust must agree.
#[test]
fn harden_test_controls_are_stripped_before_the_cap_is_applied() {
    let noisy = format!("{}payload-that-matters", "\u{0}".repeat(32));

    // Truncate-first would keep only 8 NULs, strip them, and emit "...".
    assert_eq!(harden_value(&json!(noisy), LIMITS, 0), json!("payload-..."));
}

/// CR survives hardening: `\r\n` line endings are legitimate content, and
/// Python, Go and TypeScript all preserve them. Stripping `\r` only in Rust
/// would diverge attribute values and governance-receipt digests across SDKs.
#[test]
fn harden_test_carriage_returns_tabs_and_newlines_are_preserved() {
    let limits = HardenLimits {
        max_value_length: 0,
        ..LIMITS
    };

    assert_eq!(
        harden_value(&json!("line1\r\nline2\tend\r"), limits, 0),
        json!("line1\r\nline2\tend\r")
    );
}

/// C1 controls (U+0080–U+009F) are outside the stripped set — Python's regex
/// stops at `\x7f`, so NEL (U+0085) and CSI (U+009B) must pass through here
/// too. This is why `char::is_control()` cannot be used.
#[test]
fn harden_test_c1_controls_are_preserved() {
    let limits = HardenLimits {
        max_value_length: 0,
        ..LIMITS
    };

    assert_eq!(
        harden_value(&json!("a\u{85}b\u{9b}c\u{80}d\u{9f}e"), limits, 0),
        json!("a\u{85}b\u{9b}c\u{80}d\u{9f}e")
    );
}

/// The full stripped set: C0 minus TAB/LF/CR, plus DEL. Character for
/// character the set Python's `_CONTROL_CHAR_RE` compiles.
#[test]
fn harden_test_the_stripped_set_is_c0_minus_whitespace_plus_del() {
    let limits = HardenLimits {
        max_value_length: 0,
        ..LIMITS
    };
    let dirty: String = ('\u{0}'..='\u{8}')
        .chain(['\u{b}', '\u{c}'])
        .chain('\u{e}'..='\u{1f}')
        .chain(['\u{7f}'])
        .flat_map(|ch| ['x', ch])
        .chain(['x'])
        .collect();

    let stripped = "x".repeat(dirty.chars().filter(|ch| *ch == 'x').count());
    assert_eq!(harden_value(&json!(dirty), limits, 0), json!(stripped));
}

/// Map keys are cleaned with the *key* set (`[\x00-\x1f\x7f]`): keys are
/// rendered bare, so even TAB/LF/CR — legitimate in a value — split or
/// misalign the rendered line when they appear in a key.
#[test]
fn harden_test_control_characters_in_keys_are_stripped() {
    let limits = HardenLimits {
        max_value_length: 0,
        ..LIMITS
    };
    let forged = json!({
        "amount\n2026-08-10 [error] payment.failed": 9999,
        "ta\tb\rkey\u{7f}": true,
    });

    assert_eq!(
        harden_value(&forged, limits, 0),
        json!({ "amount2026-08-10 [error] payment.failed": 9999, "tabkey": true })
    );
}

#[test]
fn harden_test_nested_map_keys_are_cleaned_too() {
    let limits = HardenLimits {
        max_value_length: 0,
        ..LIMITS
    };
    let nested = json!({ "outer": { "in\u{1}ner": { "deep\nest": 1 } } });

    assert_eq!(
        harden_value(&nested, limits, 0),
        json!({ "outer": { "inner": { "deepest": 1 } } })
    );
}

/// Cleaning is many-to-one: a sanitized key must never displace the genuine
/// field it collides with, in either iteration order. `"trace_i\x00d"` sorts
/// before `"trace_id"` and `"zz\n"` sorts after `"zz"`, so together the two
/// maps cover the squatter-first and verbatim-first orders.
#[test]
fn harden_test_a_sanitized_key_never_displaces_a_verbatim_one() {
    let limits = HardenLimits {
        max_value_length: 0,
        ..LIMITS
    };

    let squatter_first = json!({ "trace_i\u{0}d": "forged", "trace_id": "real" });
    assert_eq!(
        harden_value(&squatter_first, limits, 0),
        json!({ "trace_id": "real" })
    );

    let verbatim_first = json!({ "zz": "real", "zz\n": "forged" });
    assert_eq!(
        harden_value(&verbatim_first, limits, 0),
        json!({ "zz": "real" })
    );
}

/// Two sanitized keys that collide keep the first — arbitrary, but a genuine
/// field is never lost to the tie-break.
#[test]
fn harden_test_two_sanitized_colliding_keys_keep_the_first() {
    let limits = HardenLimits {
        max_value_length: 0,
        ..LIMITS
    };

    // "k\u{0}ey" sorts before "k\u{1}ey"; both clean to "key".
    assert_eq!(
        harden_value(
            &json!({ "k\u{0}ey": "first", "k\u{1}ey": "second" }),
            limits,
            0
        ),
        json!({ "key": "first" })
    );
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
