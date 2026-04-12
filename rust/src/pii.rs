// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use regex::Regex;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::sync::{Mutex, OnceLock};

#[cfg(feature = "governance")]
use crate::classification::classify_key;
#[cfg(feature = "governance")]
use crate::receipts::emit_receipt;

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

fn rules() -> &'static Mutex<Vec<PIIRule>> {
    RULES.get_or_init(|| Mutex::new(Vec::new()))
}

fn custom_secret_patterns() -> &'static Mutex<Vec<(String, Regex)>> {
    CUSTOM_SECRET_PATTERNS.get_or_init(|| Mutex::new(Vec::new()))
}

fn builtin_secret_patterns() -> &'static [Regex] {
    static PATTERNS: OnceLock<Vec<Regex>> = OnceLock::new();
    PATTERNS
        .get_or_init(|| {
            vec![
                Regex::new(r"(?:AKIA|ASIA)[A-Z0-9]{16}").expect("valid regex"),
                Regex::new(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}").expect("valid regex"),
                Regex::new(r"gh[pos]_[A-Za-z0-9_]{36,}").expect("valid regex"),
                Regex::new(r"[0-9a-fA-F]{40,}").expect("valid regex"),
                Regex::new(r"[A-Za-z0-9+/]{40,}={0,2}").expect("valid regex"),
            ]
        })
        .as_slice()
}

fn is_secret(value: &Value) -> bool {
    let text = match value {
        Value::String(s) => s,
        _ => return false,
    };
    if builtin_secret_patterns().iter().any(|p| p.is_match(text)) {
        return true;
    }
    custom_secret_patterns()
        .lock()
        .expect("custom patterns lock poisoned")
        .iter()
        .any(|(_, p)| p.is_match(text))
}

/// Register a custom secret detection pattern. If *name* already exists, the
/// pattern is replaced.
pub fn register_secret_pattern(name: &str, pattern: Regex) {
    let mut patterns = custom_secret_patterns()
        .lock()
        .expect("custom patterns lock poisoned");
    if let Some(entry) = patterns.iter_mut().find(|(n, _)| n == name) {
        entry.1 = pattern;
    } else {
        patterns.push((name.to_string(), pattern));
    }
}

/// Return all secret patterns (built-in and custom).
pub fn get_secret_patterns() -> Vec<SecretPattern> {
    let mut out: Vec<SecretPattern> = builtin_secret_patterns()
        .iter()
        .enumerate()
        .map(|(i, p)| SecretPattern {
            name: format!("builtin-{i}"),
            pattern: p.clone(),
        })
        .collect();
    for (name, pattern) in custom_secret_patterns()
        .lock()
        .expect("custom patterns lock poisoned")
        .iter()
    {
        out.push(SecretPattern {
            name: name.clone(),
            pattern: pattern.clone(),
        });
    }
    out
}

/// Reset custom secret patterns — for test isolation only.
pub fn reset_secret_patterns_for_tests() {
    custom_secret_patterns()
        .lock()
        .expect("custom patterns lock poisoned")
        .clear();
}

pub fn register_pii_rule(rule: PIIRule) {
    rules().lock().expect("pii lock poisoned").push(rule);
}

pub fn replace_pii_rules(next: Vec<PIIRule>) {
    *rules().lock().expect("pii lock poisoned") = next;
}

pub fn get_pii_rules() -> Vec<PIIRule> {
    rules().lock().expect("pii lock poisoned").clone()
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
                if let Some(rule) = rules.iter().find(|rule| rule.path == child_path) {
                    if let Some(masked) = mask_value(value, &rule.mode, rule.truncate_to) {
                        out.insert(key.clone(), masked);
                    }
                    #[cfg(feature = "governance")]
                    emit_receipt(
                        &child_path.join("."),
                        &format!("{:?}", rule.mode).to_ascii_lowercase(),
                        &value.to_string(),
                    );
                    continue;
                }

                let lowered = key.to_ascii_lowercase();
                if DEFAULT_SENSITIVE
                    .iter()
                    .any(|candidate| candidate == &lowered)
                    || is_secret(value)
                {
                    out.insert(key.clone(), Value::String(REDACTED.to_string()));
                    #[cfg(feature = "governance")]
                    emit_receipt(&child_path.join("."), "redact", &value.to_string());
                    continue;
                }

                out.insert(
                    key.clone(),
                    apply_rules(value, &child_path, rules, max_depth - 1),
                );
            }
            Value::Object(out)
        }
        Value::Array(values) => Value::Array(
            values
                .iter()
                .map(|value| apply_rules(value, path, rules, max_depth - 1))
                .collect(),
        ),
        _ => node.clone(),
    }
}

pub fn sanitize_payload(payload: &Value, enabled: bool, max_depth: usize) -> Value {
    if !enabled {
        return payload.clone();
    }
    let rules = get_pii_rules();
    #[cfg_attr(not(feature = "governance"), allow(unused_mut))]
    let mut cleaned = apply_rules(payload, &[], &rules, max_depth.max(1));
    #[cfg(feature = "governance")]
    if let (Value::Object(original), Value::Object(map)) = (payload, &mut cleaned) {
        let keys: Vec<String> = original.keys().cloned().collect();
        for key in keys {
            if let Some(label) = classify_key(&key) {
                map.insert(format!("__{key}__class"), Value::String(label));
            }
        }
    }
    cleaned
}
