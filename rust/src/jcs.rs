// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! RFC 8785 (JCS) canonical JSON.
//!
//! Governance receipts hash the *canonical* form of a redacted value, not its
//! `Display` or `Debug` text. Hashing the rendered form collides across types:
//! the number `1` and the string `"1"` both print as `1`, so a receipt built on
//! them could not tell an integer field from a string one.
//!
//! JCS was specified against ECMAScript, which is why the two interesting parts
//! of this module are the ones a Rust program does not get for free. Object keys
//! sort by UTF-16 code unit, not by Unicode scalar value — the two orders
//! disagree for any key holding an astral character, because a surrogate pair
//! starts at U+D800 and so sorts *before* U+E000. And numbers render by
//! ECMAScript's `Number::toString`, which prints `2.0` as `2`, `-0.0` as `0`,
//! and switches to exponential notation at different magnitudes than Rust's
//! `Display`. `serde_json` agrees with none of that.
//!
//! `spec/receipt_fixtures.yaml` pins the result. Its vectors were produced by
//! `rfc8785`, an independent implementation, so reproducing them is evidence of
//! agreeing with the other SDKs rather than with ourselves.

use serde_json::Value;

/// Serialize a value to its RFC 8785 canonical JSON form.
pub fn canonical_json(value: &Value) -> String {
    let mut out = String::new();
    write_value(value, &mut out);
    out
}

fn write_value(value: &Value, out: &mut String) {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(flag) => out.push_str(if *flag { "true" } else { "false" }),
        // `as_f64` never fails for a number this crate can build; if it ever
        // did, NaN canonicalizes to `null`, which is the contract's spelling for
        // a value JSON cannot represent.
        Value::Number(number) => {
            out.push_str(&canonical_number(number.as_f64().unwrap_or(f64::NAN)))
        }
        Value::String(text) => write_string(text, out),
        Value::Array(items) => {
            out.push('[');
            for (index, item) in items.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                write_value(item, out);
            }
            out.push(']');
        }
        Value::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort_by(|left, right| left.encode_utf16().cmp(right.encode_utf16()));
            out.push('{');
            for (index, key) in keys.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                write_string(key, out);
                out.push(':');
                write_value(&map[*key], out);
            }
            out.push('}');
        }
    }
}

/// Write a JSON string literal using ECMAScript's `JSON.stringify` escaping:
/// the six two-character escapes, `\u00xx` for every other C0 control, and
/// literal UTF-8 for everything else — including DEL, which is not escaped.
fn write_string(text: &str, out: &mut String) {
    out.push('"');
    for ch in text.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            control if control < '\u{20}' => {
                out.push_str(&format!("\\u{:04x}", control as u32));
            }
            other => out.push(other),
        }
    }
    out.push('"');
}

/// Render a binary64 the way ECMAScript's `Number::toString` does.
///
/// NaN and ±Infinity have no JSON encoding, so they become `null` — the
/// spelling `spec/receipt_fixtures.yaml`'s `non_finite_normalization` case fixes
/// for every SDK, rather than leaving each one to invent its own.
pub fn canonical_number(value: f64) -> String {
    if !value.is_finite() {
        return "null".to_string();
    }
    // Catches -0.0 as well, which JCS requires to render as `0`. Python's
    // json.dumps emits "-0.0" here, which is why the fixtures were derived with
    // a real JCS implementation instead.
    if value == 0.0 {
        return "0".to_string();
    }
    // A sign predicate rather than `< 0.0`: -0.0 already returned above, so
    // the two agree everywhere this line can see, and the predicate leaves no
    // boundary for an equivalent `<=` mutant to hide in.
    if value.is_sign_negative() {
        return format!("-{}", canonical_number(-value));
    }

    // Rust's `{:e}` yields the shortest digit string that round-trips, which is
    // exactly the `s` and `n` ECMAScript's algorithm asks for: `s` is the
    // mantissa's digits and `n` is one past the printed exponent.
    let scientific = format!("{value:e}");
    let (mantissa, exponent) = scientific
        .split_once('e')
        .expect("Rust renders a finite f64 as <mantissa>e<exponent>");
    let digits: String = mantissa.chars().filter(|ch| *ch != '.').collect();
    let significant = digits.len() as i32;
    let point = exponent
        .parse::<i32>()
        .expect("Rust renders the exponent as a decimal integer")
        + 1;
    render_digits(&digits, significant, point)
}

/// Place the decimal point per ECMAScript `Number::toString` step 5 onward,
/// where `significant` is the digit count and `point` is the position of the
/// decimal point relative to the start of those digits.
fn render_digits(digits: &str, significant: i32, point: i32) -> String {
    if significant <= point && point <= 21 {
        return format!("{digits}{}", "0".repeat((point - significant) as usize));
    }
    if 0 < point && point <= 21 {
        let split = point as usize;
        return format!("{}.{}", &digits[..split], &digits[split..]);
    }
    if -6 < point && point <= 0 {
        return format!("0.{}{digits}", "0".repeat((-point) as usize));
    }
    let exponent = point - 1;
    // A negative exponent already carries its sign; a positive one does not.
    // `is_negative()` rather than `< 0`: a zero exponent means point == 1,
    // which the plain-decimal branches above always claim, so the boundary an
    // `<=` mutant would move is unreachable here.
    let sign = if exponent.is_negative() { "" } else { "+" };
    if significant == 1 {
        return format!("{digits}e{sign}{exponent}");
    }
    format!("{}.{}e{sign}{exponent}", &digits[..1], &digits[1..])
}

#[cfg(test)]
#[path = "jcs_tests.rs"]
mod tests;
