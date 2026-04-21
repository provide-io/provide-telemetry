// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::{BTreeMap, HashMap};
use std::sync::{Mutex, OnceLock};

pub const OVERFLOW_VALUE: &str = "__overflow__";

#[derive(Clone, Debug, PartialEq)]
pub struct CardinalityLimit {
    pub max_values: usize,
    pub ttl_seconds: f64,
}

static LIMITS: OnceLock<Mutex<BTreeMap<String, CardinalityLimit>>> = OnceLock::new();

fn limits() -> &'static Mutex<BTreeMap<String, CardinalityLimit>> {
    LIMITS.get_or_init(|| Mutex::new(BTreeMap::new()))
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
}

/// Enforce cardinality limits on an attribute map.
/// Values that exceed the registered per-key limit are replaced with `OVERFLOW_VALUE`.
pub fn guard_attributes(attributes: HashMap<String, String>) -> HashMap<String, String> {
    let snapshot = limits().lock().expect("cardinality lock poisoned").clone();
    if snapshot.is_empty() {
        return attributes;
    }
    let mut seen_counts: HashMap<String, usize> = HashMap::new();
    let mut out = HashMap::new();
    for (key, value) in attributes {
        if let Some(limit) = snapshot.get(&key) {
            let count = seen_counts.entry(key.clone()).or_insert(0);
            if *count < limit.max_values {
                *count += 1;
                out.insert(key, value);
            } else {
                out.insert(key, OVERFLOW_VALUE.to_string());
            }
        } else {
            out.insert(key, value);
        }
    }
    out
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
}
