// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use regex::Regex;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::sync::{Mutex, OnceLock};

use crate::classification::{classify_key, get_classification_policy};
use crate::receipts::record_redaction;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PIIMode {
    Drop,
    Redact,
    Hash,
    Truncate,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PIIRule {
    pub path: Vec<String>,
    pub mode: PIIMode,
    pub truncate_to: usize,
}

impl PIIRule {
    pub fn new(path: Vec<String>, mode: PIIMode, truncate_to: usize) -> Self {
        Self {
            path,
            mode,
            truncate_to,
        }
    }
}

const REDACTED: &str = "***";
const TRUNC_SUFFIX: &str = "...";
const DEFAULT_SENSITIVE: &[&str] = &[
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "credential",
    "private_key",
    "ssn",
    "credit_card",
    "creditcard",
    "cvv",
    "pin",
    "account_number",
    "cookie",
];

/// A secret pattern with a diagnostic name and the compiled regex.
#[derive(Clone, Debug)]
pub struct SecretPattern {
    pub name: String,
    pub pattern: Regex,
}

static RULES: OnceLock<Mutex<Vec<PIIRule>>> = OnceLock::new();
static CUSTOM_SECRET_PATTERNS: OnceLock<Mutex<Vec<(String, Regex)>>> = OnceLock::new();

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only rewrite Vec::new() syntax.
fn empty_pii_rules_mutex() -> Mutex<Vec<PIIRule>> {
    Mutex::new(Vec::new())
}

fn rules() -> &'static Mutex<Vec<PIIRule>> {
    RULES.get_or_init(empty_pii_rules_mutex)
}

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only rewrite Vec::new() syntax.
fn empty_custom_patterns_mutex() -> Mutex<Vec<(String, Regex)>> {
    Mutex::new(Vec::new())
}

fn custom_secret_patterns() -> &'static Mutex<Vec<(String, Regex)>> {
    CUSTOM_SECRET_PATTERNS.get_or_init(empty_custom_patterns_mutex)
}

fn compiled_builtin_secret_patterns() -> Vec<Regex> {
    crate::secret_patterns_generated::PATTERNS
        .iter()
        .map(|(_name, pattern)| Regex::new(pattern).expect("generated pattern must be valid"))
        .collect()
}

fn builtin_secret_patterns() -> &'static [Regex] {
    static COMPILED: OnceLock<Vec<Regex>> = OnceLock::new();
    COMPILED
        .get_or_init(compiled_builtin_secret_patterns)
        .as_slice()
}

fn is_secret(value: &Value) -> bool {
    let text = match value {
        Value::String(s) => s,
        _ => return false,
    };
    detect_secret_in_string(text)
}

/// Returns true when *text* matches any built-in or custom secret pattern.
/// Used by the logger pipeline to scrub free-form message strings (which
/// the map-based [`sanitize_payload`] engine doesn't see).
pub(crate) fn detect_secret_in_string(text: &str) -> bool {
    secret_span(text).is_some()
}

/// How many slash-separated parts a span needs before its shape reads as a path.
const PATH_MIN_SEGMENTS: usize = 3;

/// True when a matched span is a filesystem path rather than a secret.
///
/// The long_base64 pattern is `[A-Za-z0-9+/]{40,}` and `/` belongs to the
/// base64 alphabet, so any deep path of unpunctuated segments matched it:
/// `/home/deploy/apps/production/current/lib/service` is 48 characters of pure
/// base64 alphabet containing no secret. Narrowing the charset is not the fix —
/// dropping `/` costs 44% of detections on 32-byte secrets, because a 44-char
/// base64 string holding one slash cannot be told from a path by charset alone.
///
/// Shape separates them: a path carries several short all-lowercase words
/// (usr, local, lib), which random base64 effectively never yields — a
/// 20-character all-lowercase run has probability (26/64)^20, about 1e-8.
fn looks_like_path(span: &str) -> bool {
    let segments: Vec<&str> = span.split('/').filter(|s| !s.is_empty()).collect();
    if segments.len() < PATH_MIN_SEGMENTS {
        return false;
    }
    let wordy = segments
        .iter()
        .filter(|s| !s.is_empty() && s.chars().all(|c| c.is_ascii_lowercase()))
        .count();
    wordy * 2 >= segments.len()
}

/// Byte span of the first secret-looking match, or None.
fn secret_span(text: &str) -> Option<(usize, usize)> {
    if text.len() < crate::secret_patterns_generated::MIN_SECRET_LENGTH {
        return None;
    }
    for pattern in builtin_secret_patterns() {
        if let Some(m) = pattern.find(text) {
            if !looks_like_path(m.as_str()) {
                return Some((m.start(), m.end()));
            }
        }
    }
    let patterns = crate::_lock::lock(custom_secret_patterns());
    for (_, pattern) in patterns.iter() {
        if let Some(m) = pattern.find(text) {
            if !looks_like_path(m.as_str()) {
                return Some((m.start(), m.end()));
            }
        }
    }
    None
}

/// Replace only the secret-looking token of *text*, leaving the rest readable.
///
/// The match is widened to its whitespace-delimited token first. Redacting the
/// literal match alone can leave part of a credential behind: the jwt pattern
/// matches header.payload, and a JWT has THREE dot-separated parts, so the
/// signature would survive. Whitespace is the boundary a secret cannot cross
/// without ceasing to be one token.
pub(crate) fn redact_secret_spans(text: &str) -> String {
    let Some((mut start, mut end)) = secret_span(text) else {
        return text.to_string();
    };
    while start > 0 && !text.as_bytes()[start - 1].is_ascii_whitespace() {
        start -= 1;
    }
    while end < text.len() && !text.as_bytes()[end].is_ascii_whitespace() {
        end += 1;
    }
    format!("{}{}{}", &text[..start], REDACTED, &text[end..])
}

/// The redaction sentinel emitted when a value or string matches a
/// secret pattern (matches Python's `***` and Go's `piicore.Redacted`).
pub(crate) const REDACTED_SENTINEL: &str = REDACTED;

/// Register a custom secret detection pattern. If *name* already exists, the
/// pattern is replaced.
pub fn register_secret_pattern(name: &str, pattern: Regex) {
    let mut patterns = crate::_lock::lock(custom_secret_patterns());
    if let Some((_, existing)) = patterns
        .iter_mut()
        .find(|(existing_name, _)| existing_name == name)
    {
        *existing = pattern;
    } else {
        patterns.push((name.to_string(), pattern));
    }
}

/// Return all secret patterns (built-in and custom).
pub fn get_secret_patterns() -> Vec<SecretPattern> {
    let mut out: Vec<SecretPattern> = crate::secret_patterns_generated::PATTERNS
        .iter()
        .zip(builtin_secret_patterns().iter())
        .map(|((name, _), p)| SecretPattern {
            name: name.to_string(),
            pattern: p.clone(),
        })
        .collect();
    let patterns = crate::_lock::lock(custom_secret_patterns());
    for (name, pattern) in patterns.iter() {
        out.push(SecretPattern {
            name: name.clone(),
            pattern: pattern.clone(),
        });
    }
    out
}

/// Reset custom secret patterns — for test isolation only.
pub fn reset_secret_patterns_for_tests() {
    crate::_lock::lock(custom_secret_patterns()).clear();
}

pub fn register_pii_rule(rule: PIIRule) {
    crate::_lock::lock(rules()).push(rule);
}

pub fn replace_pii_rules(next: Vec<PIIRule>) {
    *crate::_lock::lock(rules()) = next;
}

pub fn get_pii_rules() -> Vec<PIIRule> {
    crate::_lock::lock(rules()).clone()
}

fn hash_value(value: &Value) -> String {
    let mut hasher = Sha256::new();
    match value {
        Value::String(text) => hasher.update(text.as_bytes()),
        _ => hasher.update(value.to_string().as_bytes()),
    }
    let digest = hasher.finalize();
    format!("{:x}", digest)[..12].to_string()
}

fn mask_value(value: &Value, mode: &PIIMode, truncate_to: usize) -> Option<Value> {
    match mode {
        PIIMode::Drop => None,
        PIIMode::Redact => Some(Value::String(REDACTED.to_string())),
        PIIMode::Hash => Some(Value::String(hash_value(value))),
        PIIMode::Truncate => {
            let text = match value {
                Value::String(value) => value.clone(),
                _ => value.to_string(),
            };
            let char_count = text.chars().count();
            if char_count <= truncate_to {
                Some(Value::String(text))
            } else {
                let head: String = text.chars().take(truncate_to).collect();
                Some(Value::String(format!("{head}{TRUNC_SUFFIX}")))
            }
        }
    }
}

/// Segment-wise path match: `"*"` in *rule_path* matches any single segment.
fn match_rule_path(rule_path: &[String], child_path: &[String]) -> bool {
    if rule_path.len() != child_path.len() {
        return false;
    }
    rule_path
        .iter()
        .zip(child_path.iter())
        .all(|(rp, cp)| rp == "*" || rp == cp)
}

fn apply_rules(node: &Value, path: &[String], rules: &[PIIRule], max_depth: usize) -> Value {
    if max_depth == 0 {
        return node.clone();
    }

    match node {
        Value::Object(map) => {
            let mut out = Map::new();
            for (key, value) in map {
                let mut child_path = path.to_vec();
                child_path.push(key.clone());
                if let Some(rule) = rules
                    .iter()
                    .find(|rule| match_rule_path(&rule.path, &child_path))
                {
                    if let Some(masked) = mask_value(value, &rule.mode, rule.truncate_to) {
                        out.insert(key.clone(), masked);
                    }
                    record_redaction(
                        &child_path.join("."),
                        &format!("{:?}", rule.mode).to_ascii_lowercase(),
                        value,
                    );
                    continue;
                }

                let lowered = key.to_ascii_lowercase();
                if DEFAULT_SENSITIVE
                    .iter()
                    .any(|candidate| candidate == &lowered)
                    || is_secret(value)
                {
                    // Span-scoped for a secret-bearing string: only the
                    // credential token goes. A sensitive KEY still blanks
                    // wholesale, since there the whole value is the secret.
                    let replacement = match value {
                        Value::String(text) if !DEFAULT_SENSITIVE.iter().any(|c| c == &lowered) => {
                            redact_secret_spans(text)
                        }
                        _ => REDACTED.to_string(),
                    };
                    out.insert(key.clone(), Value::String(replacement));
                    record_redaction(&child_path.join("."), "redact", value);
                    continue;
                }

                out.insert(
                    key.clone(),
                    apply_rules(value, &child_path, rules, max_depth - 1),
                );
            }
            Value::Object(out)
        }
        // Fix 5: push "*" as path segment when recursing into array elements so
        // rules like ["users", "*", "email"] can match each element's "email" key.
        Value::Array(values) => {
            let mut star_path = path.to_vec();
            star_path.push("*".to_string());
            Value::Array(
                values
                    .iter()
                    .map(|value| apply_rules(value, &star_path, rules, max_depth - 1))
                    .collect(),
            )
        }
        _ => node.clone(),
    }
}

fn annotate_governance_classes(cleaned: &mut Value) {
    let Value::Object(map) = cleaned else {
        return;
    };
    let policy = get_classification_policy();
    let keys: Vec<String> = map.keys().cloned().collect();
    for key in keys {
        if let Some(label) = classify_key(&key) {
            let action = policy.lookup_action(&label);
            if action == "drop" {
                map.remove(&key);
                continue;
            }
            if matches!(action, "redact" | "hash" | "truncate") {
                let current = map
                    .get(&key)
                    .cloned()
                    .expect("classification key snapshot must still exist");
                let already_redacted = current.as_str().map(|s| s == REDACTED).unwrap_or(false);
                if !already_redacted {
                    let mode = match action {
                        "redact" => PIIMode::Redact,
                        "hash" => PIIMode::Hash,
                        _ => PIIMode::Truncate,
                    };
                    let masked = mask_value(&current, &mode, 8)
                        .expect("classification governance modes never drop values");
                    map.insert(key.clone(), masked);
                }
            }
            map.insert(format!("__{key}__class"), Value::String(label));
        }
    }
}

pub fn sanitize_payload(payload: &Value, enabled: bool, max_depth: usize) -> Value {
    if !enabled {
        return payload.clone();
    }
    let rules = get_pii_rules();
    let mut cleaned = apply_rules(payload, &[], &rules, max_depth.max(1));
    annotate_governance_classes(&mut cleaned);
    cleaned
}

#[cfg(test)]
#[path = "pii_tests.rs"]
mod tests;
