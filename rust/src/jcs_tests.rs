// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use super::*;

use serde_json::json;

/// The whole point of canonicalizing before hashing: a display-form digest
/// cannot tell these two apart.
#[test]
fn jcs_test_a_number_and_its_string_spelling_differ() {
    assert_ne!(canonical_json(&json!(1)), canonical_json(&json!("1")));
}

#[test]
fn jcs_test_scalars_render_in_their_json_form() {
    assert_eq!(canonical_json(&Value::Null), "null");
    assert_eq!(canonical_json(&json!(true)), "true");
    assert_eq!(canonical_json(&json!(false)), "false");
    assert_eq!(canonical_json(&json!("plain")), "\"plain\"");
}

#[test]
fn jcs_test_escapes_follow_json_stringify() {
    assert_eq!(
        canonical_json(&json!("q\"b\\s\u{08}f\u{0c}n\nr\rt\t")),
        r#""q\"b\\s\bf\fn\nr\rt\t""#
    );
    // Every other C0 control takes the \u00xx form; DEL is not escaped at all.
    assert_eq!(
        canonical_json(&json!("\u{01}\u{1f}\u{7f}")),
        "\"\\u0001\\u001f\u{7f}\""
    );
}

/// Key order is by UTF-16 code unit, not by Unicode scalar value. An astral
/// character encodes as a surrogate pair starting at U+D800, so it sorts
/// *before* U+E000 — the opposite of what comparing Rust `String`s would give.
#[test]
fn jcs_test_object_keys_sort_by_utf16_code_unit() {
    let value = json!({ "\u{e000}": 1, "\u{1f600}": 2 });

    assert_eq!(canonical_json(&value), "{\"\u{1f600}\":2,\"\u{e000}\":1}");
    // Guard the claim: plain scalar-value ordering would have put them the
    // other way round.
    assert!("\u{e000}" < "\u{1f600}");
}

#[test]
fn jcs_test_empty_composites_round_trip() {
    assert_eq!(canonical_json(&json!([])), "[]");
    assert_eq!(canonical_json(&json!({})), "{}");
}

#[test]
fn jcs_test_nested_composites_keep_element_order_and_sort_keys() {
    let value = json!({ "z": [1, [2, 3]], "a": { "b": 1, "A": 2 } });

    assert_eq!(
        canonical_json(&value),
        r#"{"a":{"A":2,"b":1},"z":[1,[2,3]]}"#
    );
}

#[test]
fn jcs_test_numbers_render_as_ecmascript_does() {
    // Integral values drop the fractional part, and -0 collapses onto 0.
    assert_eq!(canonical_number(2.0), "2");
    assert_eq!(canonical_number(0.0), "0");
    assert_eq!(canonical_number(-0.0), "0");
    assert_eq!(canonical_number(1.5), "1.5");
    assert_eq!(canonical_number(-1.5), "-1.5");
    // Trailing zeros are materialized up to 10^21, and only then does the
    // rendering switch to exponential notation.
    assert_eq!(canonical_number(1e20), "100000000000000000000");
    assert_eq!(canonical_number(1e21), "1e+21");
    assert_eq!(canonical_number(1.5e21), "1.5e+21");
    // Leading zeros are materialized down to 10^-6, and no further.
    assert_eq!(canonical_number(0.001), "0.001");
    assert_eq!(canonical_number(1e-6), "0.000001");
    assert_eq!(canonical_number(1e-7), "1e-7");
    assert_eq!(canonical_number(1.5e-7), "1.5e-7");
}

/// A value JSON cannot represent becomes `null` rather than each SDK inventing
/// a spelling for it.
#[test]
fn jcs_test_non_finite_numbers_normalize_to_null() {
    assert_eq!(canonical_number(f64::NAN), "null");
    assert_eq!(canonical_number(f64::INFINITY), "null");
    assert_eq!(canonical_number(f64::NEG_INFINITY), "null");
}
