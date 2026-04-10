// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use regex::Regex;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::sync::{Mutex, OnceLock};

use crate::classification::classify_key;
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

static RULES: OnceLock<Mutex<Vec<PIIRule>>> = OnceLock::new();

fn rules() -> &'static Mutex<Vec<PIIRule>> {
    RULES.get_or_init(|| Mutex::new(Vec::new()))
}

fn secret_patterns() -> &'static [Regex] {
    static PATTERNS: OnceLock<Vec<Regex>> = OnceLock::new();
    PATTERNS
        .get_or_init(|| {
            vec![
                Regex::new(r"(?:AKIA|ASIA)[A-Z0-9]{16}").expect("valid regex"),
                Regex::new(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}").expect("valid regex"),
            ]
        })
        .as_slice()
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
            if text.len() <= truncate_to {
                Some(Value::String(text))
            } else {
                Some(Value::String(format!(
                    "{}{}",
                    &text[..truncate_to],
                    TRUNC_SUFFIX
                )))
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
                    || matches!(value, Value::String(text) if secret_patterns().iter().any(|pattern| pattern.is_match(text)))
                {
                    out.insert(key.clone(), Value::String(REDACTED.to_string()));
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
    let mut cleaned = apply_rules(payload, &[], &rules, max_depth.max(1));
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
