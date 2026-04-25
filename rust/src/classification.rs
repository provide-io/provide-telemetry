// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::sync::{Mutex, OnceLock};

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub enum DataClass {
    #[default]
    Public,
    Internal,
    Pii,
    Phi,
    Pci,
    Secret,
}

impl DataClass {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Public => "PUBLIC",
            Self::Internal => "INTERNAL",
            Self::Pii => "PII",
            Self::Phi => "PHI",
            Self::Pci => "PCI",
            Self::Secret => "SECRET", // pragma: allowlist secret
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ClassificationRule {
    pub pattern: String,
    pub classification: DataClass,
}

impl ClassificationRule {
    pub fn new(pattern: impl Into<String>, classification: DataClass) -> Self {
        Self {
            pattern: pattern.into(),
            classification,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ClassificationPolicy {
    pub public: String,
    pub internal: String,
    pub pii: String,
    pub phi: String,
    pub pci: String,
    pub secret: String,
}

impl ClassificationPolicy {
    /// Return the action string for a given *label* (e.g. `"PII"`, `"PHI"`, …).
    /// Labels are the upper-case strings returned by `DataClass::as_str()`.
    /// Unknown labels fall through to `"pass"`.
    pub fn lookup_action(&self, label: &str) -> &str {
        match label {
            "PUBLIC" => &self.public,
            "INTERNAL" => &self.internal,
            "PII" => &self.pii,
            "PHI" => &self.phi,
            "PCI" => &self.pci,
            "SECRET" => &self.secret, // pragma: allowlist secret
            _ => "pass",
        }
    }
}

impl Default for ClassificationPolicy {
    fn default() -> Self {
        Self {
            public: "pass".to_string(),
            internal: "pass".to_string(),
            pii: "redact".to_string(),
            phi: "drop".to_string(),
            pci: "hash".to_string(),
            secret: "drop".to_string(), // pragma: allowlist secret
        }
    }
}

static POLICY: OnceLock<Mutex<ClassificationPolicy>> = OnceLock::new();

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only swap in Mutex::default().
fn default_policy_mutex() -> Mutex<ClassificationPolicy> {
    Mutex::new(ClassificationPolicy::default())
}

fn policy() -> &'static Mutex<ClassificationPolicy> {
    POLICY.get_or_init(default_policy_mutex)
}

pub fn set_classification_policy(p: ClassificationPolicy) {
    *crate::_lock::lock(policy()) = p;
}

pub fn get_classification_policy() -> ClassificationPolicy {
    crate::_lock::lock(policy()).clone()
}

static RULES: OnceLock<Mutex<Vec<ClassificationRule>>> = OnceLock::new();

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only rewrite Vec::new() syntax.
fn empty_rules_mutex() -> Mutex<Vec<ClassificationRule>> {
    Mutex::new(Vec::new())
}

fn rules() -> &'static Mutex<Vec<ClassificationRule>> {
    RULES.get_or_init(empty_rules_mutex)
}

/// Match *key* against *pattern* using fnmatch semantics:
/// `*` matches any sequence of characters (including empty); `?` matches
/// exactly one character.  No character-class support is needed here.
fn match_glob(pattern: &str, key: &str) -> bool {
    // Fast path: no wildcards → exact match.
    if !pattern.contains(['*', '?']) {
        return pattern == key;
    }
    // One-pass recursive matcher on byte slices (all ASCII for key names).
    fn glob_match(p: &[u8], s: &[u8]) -> bool {
        match (p.first(), s.first()) {
            // Both exhausted → full match.
            (None, None) => true,
            // Pattern exhausted but string remains → no match.
            (None, Some(_)) => false,
            // `*` — try skipping zero or more characters in s.
            (Some(b'*'), _) => {
                let p_rest = &p[1..];
                // Try matching p_rest against every suffix of s (including empty).
                for offset in 0..=s.len() {
                    if glob_match(p_rest, &s[offset..]) {
                        return true;
                    }
                }
                false
            }
            // `?` matches any single character that exists.
            (Some(b'?'), Some(_)) => glob_match(&p[1..], &s[1..]),
            // `?` but string exhausted → no match.
            (Some(b'?'), None) => false,
            // Literal character must match exactly.
            (Some(&pc), Some(&sc)) => pc == sc && glob_match(&p[1..], &s[1..]),
            // Pattern has chars but string is empty (non-star, non-zero).
            (Some(_), None) => false,
        }
    }
    glob_match(pattern.as_bytes(), key.as_bytes())
}

pub fn register_classification_rule(rule: ClassificationRule) {
    crate::_lock::lock(rules()).push(rule);
}

pub fn register_classification_rules(next: Vec<ClassificationRule>) {
    crate::_lock::lock(rules()).extend(next);
}

pub fn clear_classification_rules() {
    crate::_lock::lock(rules()).clear();
}

pub fn classify_key(key: &str) -> Option<String> {
    let rules = crate::_lock::lock(rules());
    for rule in rules.iter() {
        if match_glob(&rule.pattern, key) {
            return Some(rule.classification.as_str().to_string());
        }
    }
    None
}

#[cfg(test)]
#[path = "classification_tests.rs"]
mod tests;
