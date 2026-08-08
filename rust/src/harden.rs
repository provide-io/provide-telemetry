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

fn should_keep_char(ch: char) -> bool {
    match ch {
        // Newlines and tabs are legitimate content in a message or a stack
        // trace; every other control character can forge a log line.
        '\n' | '\t' => true,
        _ => !ch.is_control(),
    }
}

fn strip_control_chars(value: &mut String) {
    value.retain(should_keep_char);
}

fn harden_string(text: &str, max_value_length: usize) -> String {
    let mut cleaned = text.to_string();
    truncate_string_value(&mut cleaned, max_value_length);
    strip_control_chars(&mut cleaned);
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
            let mut out = Map::new();
            for (key, nested) in retained_entries(map, limits.max_attr_count) {
                out.insert(key.clone(), harden_value(nested, limits, depth + 1));
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
