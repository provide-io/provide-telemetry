// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;
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
