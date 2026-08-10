// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Recursive input hardening — the structural stage of the signal pipeline.
//!
//! Separate from `pii.rs` because it is a different kind of work: `pii.rs`
//! decides *policy* (which fields are sensitive and what to do with them),
//! while this decides *shape* (how deep, how wide, how long). Hardening runs
//! first, so PII traversal, receipt canonicalization, local rendering and the
//! OTel bridge all operate on a value that is already bounded.
//!
//! Before this existed, Rust hardened only the top level of a log event's
//! context: one pass of truncation and control-character stripping over
//! top-level strings, plus an attribute-count cap. A nested map went to the
//! exporter unbounded in depth, width and value length, and
//! `PROVIDE_SECURITY_MAX_NESTING_DEPTH` was parsed into a field nothing read.
//!
//! Two of the hazards the TypeScript and Python engines must handle cannot
//! arise here, and so have no code: `serde_json::Value` is an owned tree, so it
//! can hold neither a cycle nor a shared subtree, and every `Value` has a JSON
//! representation by construction — `Number` cannot even be built from NaN.

use serde_json::{Map, Value};

use crate::pii::REDACTED_SENTINEL;

const TRUNCATION_MARKER: &str = "...";

/// The structural bounds applied at every level of a value.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct HardenLimits {
    /// Byte ceiling for a single string. 0 disables truncation.
    pub max_value_length: usize,
    /// Ceiling on keys retained per map. 0 disables the cap.
    pub max_attr_count: usize,
    /// Nesting a composite may not reach. A map or array at this depth
    /// collapses to the redaction sentinel instead of being traversed.
    pub max_depth: usize,
}

/// Truncate on a character boundary and append a marker, so a caller reading
/// the record can tell a shortened value from a genuinely short one.
fn truncate_string_value(value: &mut String, max_value_length: usize) {
    if max_value_length == 0 || value.len() <= max_value_length {
        return;
    }
    let cutoff = value
        .char_indices()
        .map(|(index, ch)| index + ch.len_utf8())
        .take_while(|end| *end <= max_value_length)
        .last()
        .unwrap_or(0);
    value.truncate(cutoff);
    value.push_str(TRUNCATION_MARKER);
}

/// True for a character a hardened string *value* drops.
///
/// The set is exactly `[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]` — C0 controls except
/// TAB/LF/CR, plus DEL — the same one Python's `_CONTROL_CHAR_RE`, Go's
/// `hardenString` and TypeScript's `_CONTROL_CHARS` compile. TAB, LF and CR
/// are legitimate content in a message or a stack trace. `char::is_control()`
/// is deliberately not used: it is the Unicode Cc category, which also covers
/// C1 (U+0080–U+009F), so the same attribute would export with different
/// bytes — and a different governance-receipt digest — depending on which SDK
/// hardened it (see `propagation.rs` for the same reasoning at the baggage
/// boundary).
fn should_strip_value_char(ch: char) -> bool {
    matches!(ch, '\x00'..='\x08' | '\x0b' | '\x0c' | '\x0e'..='\x1f' | '\x7f')
}

/// True for a character a hardened map *key* drops.
///
/// The set is `[\x00-\x1f\x7f]` — Python's `_CONTROL_CHAR_KEY_RE`. Keys are
/// rendered bare by the console renderer, so unlike values they cannot keep
/// TAB, LF or CR: any of the three splits or misaligns the rendered line.
fn should_strip_key_char(ch: char) -> bool {
    matches!(ch, '\x00'..='\x1f' | '\x7f')
}

/// Strip every key-forbidden control character from an attribute key.
/// Mirrors Python's `_clean_key`.
pub(crate) fn clean_key(key: &str) -> String {
    key.chars()
        .filter(|ch| !should_strip_key_char(*ch))
        .collect()
}

/// Whether an entry whose cleaned key is `name` may claim (or reclaim) the
/// slot for `name`. Mirrors Python's `_harden_keys` collision policy: cleaning
/// is many-to-one, so a key that needed cleaning never displaces one already
/// present, while a key that needed no cleaning always wins over a sanitized
/// squatter — otherwise a forged `"trace_i\x00d"` payload key could replace
/// the genuine `trace_id` and correlate the record to an attacker-chosen
/// trace. Two sanitized keys that collide keep the first.
pub(crate) fn cleaned_key_claims_slot(
    occupied: bool,
    untouched: bool,
    holder_is_verbatim: bool,
) -> bool {
    !occupied || (untouched && !holder_is_verbatim)
}

fn harden_string(text: &str, max_value_length: usize) -> String {
    // Strip first, then truncate: the cap must count characters a reader will
    // actually see. Truncating first lets a control-heavy prefix eat the whole
    // budget and collapse the value to just the marker — and it is the order
    // Python, Go and TypeScript already share.
    let mut cleaned: String = text
        .chars()
        .filter(|ch| !should_strip_value_char(*ch))
        .collect();
    truncate_string_value(&mut cleaned, max_value_length);
    cleaned
}

fn redacted() -> Value {
    Value::String(REDACTED_SENTINEL.to_string())
}

/// Bound `value` to a finite shape, treating it as sitting at `depth`.
///
/// A composite at or past `max_depth` collapses to `"***"` rather than being
/// passed through: an unbounded structure reaching a serializer is the failure
/// this stage exists to prevent, so the depth ceiling has to be a refusal and
/// not a stop-recursing-but-emit-anyway.
pub(crate) fn harden_value(value: &Value, limits: HardenLimits, depth: usize) -> Value {
    match value {
        Value::String(text) => Value::String(harden_string(text, limits.max_value_length)),
        Value::Array(items) => {
            if depth >= limits.max_depth {
                return redacted();
            }
            Value::Array(
                items
                    .iter()
                    .map(|item| harden_value(item, limits, depth + 1))
                    .collect(),
            )
        }
        Value::Object(map) => {
            if depth >= limits.max_depth {
                return redacted();
            }
            // Keys are hardened as well as values: the console renderer quotes
            // values but emits keys bare, so a control character in a key
            // would forge a second log line. Cleaning goes through the
            // `_harden_keys` collision policy — see `cleaned_key_claims_slot`.
            let mut out = Map::new();
            let mut verbatim: std::collections::BTreeSet<String> =
                std::collections::BTreeSet::new();
            for (key, nested) in retained_entries(map, limits.max_attr_count) {
                let name = clean_key(key);
                let untouched = name == *key;
                if !cleaned_key_claims_slot(
                    out.contains_key(&name),
                    untouched,
                    verbatim.contains(&name),
                ) {
                    continue;
                }
                out.insert(name.clone(), harden_value(nested, limits, depth + 1));
                if untouched {
                    verbatim.insert(name);
                }
            }
            Value::Object(out)
        }
        scalar => scalar.clone(),
    }
}

/// The entries a map keeps under the width cap. A cap of 0 means unlimited,
/// matching how `PROVIDE_SECURITY_MAX_ATTR_COUNT` is read everywhere else.
fn retained_entries(
    map: &Map<String, Value>,
    max_attr_count: usize,
) -> impl Iterator<Item = (&String, &Value)> {
    let limit = if max_attr_count == 0 {
        map.len()
    } else {
        max_attr_count
    };
    map.iter().take(limit)
}

#[cfg(test)]
#[path = "harden_tests.rs"]
mod tests;
