// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::HashMap;
use std::thread;
use std::time::Duration;

use provide_telemetry::cardinality::OVERFLOW_VALUE;
use provide_telemetry::testing::{acquire_test_state_lock, reset_telemetry_state};
use provide_telemetry::{CardinalityLimit, guard_attributes, register_cardinality_limit};

#[test]
fn cardinality_test_overflows_after_max_distinct_values_seen_for_key() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    register_cardinality_limit(
        "user.id",
        CardinalityLimit {
            max_values: 1,
            ttl_seconds: 60.0,
        },
    );

    let first = guard_attributes(HashMap::from([("user.id".to_string(), "u-1".to_string())]));
    assert_eq!(first.get("user.id").map(String::as_str), Some("u-1"));

    let second = guard_attributes(HashMap::from([("user.id".to_string(), "u-2".to_string())]));
    assert_eq!(
        second.get("user.id").map(String::as_str),
        Some(OVERFLOW_VALUE)
    );
}

#[test]
fn cardinality_test_reuses_existing_seen_value_without_overflow() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    register_cardinality_limit(
        "tenant.id",
        CardinalityLimit {
            max_values: 1,
            ttl_seconds: 60.0,
        },
    );

    let first = guard_attributes(HashMap::from([(
        "tenant.id".to_string(),
        "tenant-a".to_string(),
    )]));
    assert_eq!(first.get("tenant.id").map(String::as_str), Some("tenant-a"));

    let second = guard_attributes(HashMap::from([(
        "tenant.id".to_string(),
        "tenant-a".to_string(),
    )]));
    assert_eq!(
        second.get("tenant.id").map(String::as_str),
        Some("tenant-a")
    );
}

#[test]
fn cardinality_test_guard_attributes_returns_expected_keys() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    register_cardinality_limit(
        "env",
        CardinalityLimit {
            max_values: 2,
            ttl_seconds: 60.0,
        },
    );

    let guarded = guard_attributes(HashMap::from([
        ("env".to_string(), "prod".to_string()),
        ("region".to_string(), "us-east".to_string()),
    ]));

    assert_eq!(guarded.len(), 2);
    assert_eq!(guarded.get("env").map(String::as_str), Some("prod"));
    assert_eq!(guarded.get("region").map(String::as_str), Some("us-east"));
    assert!(!guarded.contains_key("xyzzy"));
}

#[test]
fn cardinality_test_ttl_expiry_reopens_capacity_for_new_value() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    register_cardinality_limit(
        "session.id",
        CardinalityLimit {
            max_values: 1,
            ttl_seconds: 1.0,
        },
    );

    let first = guard_attributes(HashMap::from([(
        "session.id".to_string(),
        "s-1".to_string(),
    )]));
    assert_eq!(first.get("session.id").map(String::as_str), Some("s-1"));

    let overflow = guard_attributes(HashMap::from([(
        "session.id".to_string(),
        "s-2".to_string(),
    )]));
    assert_eq!(
        overflow.get("session.id").map(String::as_str),
        Some(OVERFLOW_VALUE)
    );

    thread::sleep(Duration::from_millis(5100));

    let after_ttl = guard_attributes(HashMap::from([(
        "session.id".to_string(),
        "s-3".to_string(),
    )]));
    assert_eq!(after_ttl.get("session.id").map(String::as_str), Some("s-3"));
}
