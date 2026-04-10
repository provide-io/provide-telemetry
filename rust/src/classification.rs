// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::sync::{Mutex, OnceLock};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DataClass {
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

#[derive(Clone, Debug, PartialEq, Eq)]
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

static RULES: OnceLock<Mutex<Vec<ClassificationRule>>> = OnceLock::new();

fn rules() -> &'static Mutex<Vec<ClassificationRule>> {
    RULES.get_or_init(|| Mutex::new(Vec::new()))
}

fn match_glob(pattern: &str, key: &str) -> bool {
    if let Some((prefix, "")) = pattern.split_once('*') {
        return key.starts_with(prefix);
    }
    pattern == key
}

pub fn register_classification_rule(rule: ClassificationRule) {
    rules()
        .lock()
        .expect("classification lock poisoned")
        .push(rule);
}

pub fn register_classification_rules(next: Vec<ClassificationRule>) {
    rules()
        .lock()
        .expect("classification lock poisoned")
        .extend(next);
}

pub fn clear_classification_rules() {
    rules()
        .lock()
        .expect("classification lock poisoned")
        .clear();
}

pub fn classify_key(key: &str) -> Option<String> {
    rules()
        .lock()
        .expect("classification lock poisoned")
        .iter()
        .find(|rule| match_glob(&rule.pattern, key))
        .map(|rule| rule.classification.as_str().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testing::acquire_test_state_lock;

    #[test]
    fn classification_test_clear_rules_removes_registered_matches() {
        let _guard = acquire_test_state_lock();
        clear_classification_rules();
        register_classification_rule(ClassificationRule::new("email*", DataClass::Pii));
        assert_eq!(classify_key("email_address").as_deref(), Some("PII"));

        clear_classification_rules();

        assert_eq!(classify_key("email_address"), None);
    }
}
