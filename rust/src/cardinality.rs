// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::{BTreeMap, HashMap};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

pub const OVERFLOW_VALUE: &str = "__overflow__";

const PRUNE_INTERVAL: Duration = Duration::from_secs(5);

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CardinalityLimit {
    pub max_values: usize,
    pub ttl_seconds: f64,
}

#[derive(Default)]
struct CardinalityState {
    limits: BTreeMap<String, CardinalityLimit>,
    seen: HashMap<String, HashMap<String, Instant>>,
    last_prune: HashMap<String, Instant>,
}

static STATE: OnceLock<Mutex<CardinalityState>> = OnceLock::new();

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only swap in Mutex::default().
fn default_cardinality_state_mutex() -> Mutex<CardinalityState> {
    Mutex::new(CardinalityState::default())
}

fn state() -> &'static Mutex<CardinalityState> {
    STATE.get_or_init(default_cardinality_state_mutex)
}

pub fn register_cardinality_limit(key: impl Into<String>, limit: CardinalityLimit) {
    let key = key.into();
    let mut guard = crate::_lock::lock(state());
    guard.limits.insert(
        key.clone(),
        CardinalityLimit {
            max_values: limit.max_values.max(1),
            ttl_seconds: limit.ttl_seconds.max(1.0),
        },
    );
    guard.seen.entry(key).or_default();
}

pub fn get_cardinality_limits() -> BTreeMap<String, CardinalityLimit> {
    crate::_lock::lock(state()).limits.clone()
}

pub fn clear_cardinality_limits() {
    let mut guard = crate::_lock::lock(state());
    guard.limits.clear();
    guard.seen.clear();
    guard.last_prune.clear();
}

fn should_prune(last_prune: Option<Instant>, now: Instant) -> bool {
    last_prune
        .map(|last| now.duration_since(last) >= PRUNE_INTERVAL)
        .unwrap_or(true)
}

fn prune_expired_values(seen: &mut HashMap<String, Instant>, ttl_seconds: f64, now: Instant) {
    let ttl = Duration::from_secs_f64(ttl_seconds.max(1.0));
    seen.retain(|_, seen_at| now.duration_since(*seen_at) < ttl);
}

/// Enforce cardinality limits on an attribute map.
/// Values that exceed the registered per-key limit are replaced with `OVERFLOW_VALUE`.
pub fn guard_attributes(attributes: HashMap<String, String>) -> HashMap<String, String> {
    let now = Instant::now();
    let mut out = HashMap::with_capacity(attributes.len());

    for (key, value) in attributes {
        let mut guard = crate::_lock::lock(state());
        let Some(limit) = guard.limits.get(&key).cloned() else {
            out.insert(key, value);
            continue;
        };

        let last_prune = guard.last_prune.get(&key).copied();
        let prune_now = should_prune(last_prune, now);

        if prune_now {
            let seen = guard.seen.entry(key.clone()).or_default();
            prune_expired_values(seen, limit.ttl_seconds, now);
            guard.last_prune.insert(key.clone(), now);
        }

        let seen = guard.seen.entry(key.clone()).or_default();

        if seen.contains_key(&value) {
            seen.insert(value.clone(), now);
            out.insert(key, value);
            continue;
        }

        if seen.len() >= limit.max_values {
            out.insert(key, OVERFLOW_VALUE.to_string());
            continue;
        }

        seen.insert(value.clone(), now);
        out.insert(key, value);
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

    #[test]
    fn cardinality_test_a_get_limits_returns_registered_clamped_values() {
        let _guard = acquire_test_state_lock();
        clear_cardinality_limits();
        register_cardinality_limit(
            "tenant.id",
            CardinalityLimit {
                max_values: 0,
                ttl_seconds: 0.0,
            },
        );

        let limits = get_cardinality_limits();
        let limit = limits.get("tenant.id").expect("limit should exist");
        assert_eq!(limit.max_values, 1);
        assert_eq!(limit.ttl_seconds, 1.0);
        assert_eq!(limits.len(), 1);
    }

    #[test]
    fn cardinality_test_should_prune_false_before_interval() {
        let now = Instant::now();
        assert!(!should_prune(Some(now - Duration::from_secs(1)), now));
    }

    #[test]
    fn cardinality_test_should_prune_true_without_previous_prune() {
        assert!(should_prune(None, Instant::now()));
    }

    #[test]
    fn cardinality_test_prune_expired_values_drops_exact_ttl_boundary() {
        let now = Instant::now();
        let mut seen = HashMap::from([
            ("fresh".to_string(), now - Duration::from_millis(500)),
            ("boundary".to_string(), now - Duration::from_secs(1)),
            ("expired".to_string(), now - Duration::from_secs(2)),
        ]);

        prune_expired_values(&mut seen, 1.0, now);

        assert!(seen.contains_key("fresh"));
        assert!(!seen.contains_key("boundary"));
        assert!(!seen.contains_key("expired"));
    }

    #[test]
    fn cardinality_test_guard_attributes_prunes_before_capacity_check() {
        let _guard = acquire_test_state_lock();
        clear_cardinality_limits();
        register_cardinality_limit(
            "user.id",
            CardinalityLimit {
                max_values: 1,
                ttl_seconds: 1.0,
            },
        );

        let stale_seen_at = Instant::now() - Duration::from_secs(2);
        let stale_last_prune = Instant::now() - PRUNE_INTERVAL - Duration::from_millis(1);
        {
            let mut state = crate::_lock::lock(state());
            state.seen.insert(
                "user.id".to_string(),
                HashMap::from([("stale".to_string(), stale_seen_at)]),
            );
            state
                .last_prune
                .insert("user.id".to_string(), stale_last_prune);
        }

        let result = guard_attributes(HashMap::from([(
            "user.id".to_string(),
            "fresh".to_string(),
        )]));

        assert_eq!(result.get("user.id").map(String::as_str), Some("fresh"));
        let state = crate::_lock::lock(state());
        let seen = state.seen.get("user.id").expect("seen values should exist");
        assert_eq!(seen.len(), 1);
        assert!(seen.contains_key("fresh"));
        assert!(!seen.contains_key("stale"));
    }
}
