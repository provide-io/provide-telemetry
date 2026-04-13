// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::{BTreeMap, HashMap, HashSet};
use std::sync::{Mutex, OnceLock};

pub const OVERFLOW_VALUE: &str = "__overflow__";

#[derive(Clone, Debug, PartialEq)]
pub struct CardinalityLimit {
    pub max_values: usize,
    pub ttl_seconds: f64,
}

static LIMITS: OnceLock<Mutex<BTreeMap<String, CardinalityLimit>>> = OnceLock::new();
/// Tracks the set of unique values seen per attribute key for cardinality enforcement.
static SEEN_VALUES: OnceLock<Mutex<HashMap<String, HashSet<String>>>> = OnceLock::new();

fn limits() -> &'static Mutex<BTreeMap<String, CardinalityLimit>> {
    LIMITS.get_or_init(|| Mutex::new(BTreeMap::new()))
}

fn seen_values() -> &'static Mutex<HashMap<String, HashSet<String>>> {
    SEEN_VALUES.get_or_init(|| Mutex::new(HashMap::new()))
}

pub fn register_cardinality_limit(key: impl Into<String>, limit: CardinalityLimit) {
    limits().lock().expect("cardinality lock poisoned").insert(
        key.into(),
        CardinalityLimit {
            max_values: limit.max_values.max(1),
            ttl_seconds: limit.ttl_seconds.max(1.0),
        },
    );
}

pub fn get_cardinality_limits() -> BTreeMap<String, CardinalityLimit> {
    limits().lock().expect("cardinality lock poisoned").clone()
}

pub fn clear_cardinality_limits() {
    limits().lock().expect("cardinality lock poisoned").clear();
    seen_values()
        .lock()
        .expect("cardinality seen lock poisoned")
        .clear();
}

/// Enforce registered cardinality limits on a set of attributes.
///
/// For each attribute key that has a registered limit, the value is allowed through
/// only if the number of unique values seen so far is within the limit. Once the
/// limit is exceeded, the value is replaced with [`OVERFLOW_VALUE`].
pub fn guard_attributes(attributes: HashMap<String, String>) -> HashMap<String, String> {
    let limits = limits().lock().expect("cardinality lock poisoned");
    let mut seen = seen_values()
        .lock()
        .expect("cardinality seen lock poisoned");

    attributes
        .into_iter()
        .map(|(key, value)| {
            if let Some(limit) = limits.get(&key) {
                let entry = seen.entry(key.clone()).or_default();
                if entry.contains(&value) {
                    // Already seen — pass through without counting again.
                    return (key, value);
                }
                if entry.len() >= limit.max_values {
                    // Limit exceeded — replace value with overflow sentinel.
                    return (key, OVERFLOW_VALUE.to_string());
                }
                entry.insert(value.clone());
            }
            (key, value)
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testing::acquire_test_state_lock;

    #[test]
    fn cardinality_test_clear_limits_removes_registered_entries() {
        let _guard = acquire_test_state_lock();
        clear_cardinality_limits();
        register_cardinality_limit(
            "user.id",
            CardinalityLimit {
                max_values: 5,
                ttl_seconds: 60.0,
            },
        );
        assert!(get_cardinality_limits().contains_key("user.id"));

        clear_cardinality_limits();

        assert!(get_cardinality_limits().is_empty());
    }

    #[test]
    fn cardinality_test_guard_attributes_enforces_limit_and_overflows() {
        let _guard = acquire_test_state_lock();
        clear_cardinality_limits();

        register_cardinality_limit(
            "status",
            CardinalityLimit {
                max_values: 3,
                ttl_seconds: 60.0,
            },
        );

        // First 3 unique values should pass through unchanged.
        for value in ["ok", "error", "timeout"] {
            let attrs: HashMap<String, String> = [("status".to_string(), value.to_string())]
                .into_iter()
                .collect();
            let result = guard_attributes(attrs);
            assert_eq!(
                result["status"], value,
                "value '{value}' should pass through within limit"
            );
        }

        // 4th unique value should overflow.
        let attrs: HashMap<String, String> = [("status".to_string(), "unknown".to_string())]
            .into_iter()
            .collect();
        let result = guard_attributes(attrs);
        assert_eq!(
            result["status"], OVERFLOW_VALUE,
            "4th unique value should be replaced with overflow sentinel"
        );

        // Already-seen values still pass through.
        let attrs: HashMap<String, String> = [("status".to_string(), "ok".to_string())]
            .into_iter()
            .collect();
        let result = guard_attributes(attrs);
        assert_eq!(
            result["status"], "ok",
            "previously seen value should pass through unchanged"
        );

        // Keys without limits are unaffected.
        let attrs: HashMap<String, String> = [("unregistered".to_string(), "anything".to_string())]
            .into_iter()
            .collect();
        let result = guard_attributes(attrs);
        assert_eq!(result["unregistered"], "anything");
    }
}
