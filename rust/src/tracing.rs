// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;
use std::sync::atomic::{AtomicU64, Ordering};

use crate::context::{set_trace_context_internal, trace_snapshot, ContextGuard};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Tracer {
    name: String,
}

pub static tracer: std::sync::LazyLock<Tracer> = std::sync::LazyLock::new(|| Tracer::new(None));

impl Tracer {
    pub fn new(name: Option<&str>) -> Self {
        Self {
            name: name.unwrap_or("provide.telemetry").to_string(),
        }
    }

    pub fn name(&self) -> &str {
        &self.name
    }
}

static TRACE_COUNTER: AtomicU64 = AtomicU64::new(1);

fn next_hex(len: usize) -> String {
    let seed = TRACE_COUNTER.fetch_add(1, Ordering::Relaxed);
    let mut value = format!("{seed:016x}");
    while value.len() < len {
        let snapshot = TRACE_COUNTER.fetch_add(1, Ordering::Relaxed);
        value.push_str(&format!("{snapshot:016x}"));
    }
    value[..len].to_string()
}

pub fn get_tracer(name: Option<&str>) -> Tracer {
    Tracer::new(name)
}

pub fn set_trace_context(trace_id: Option<String>, span_id: Option<String>) -> ContextGuard {
    set_trace_context_internal(trace_id, span_id)
}

pub fn get_trace_context() -> BTreeMap<String, Option<String>> {
    let snapshot = trace_snapshot();
    BTreeMap::from([
        ("trace_id".to_string(), snapshot.trace_id),
        ("span_id".to_string(), snapshot.span_id),
    ])
}

pub fn trace<T, F>(name: &str, callback: F) -> T
where
    F: FnOnce() -> T,
{
    let _span_name = name;
    let _guard = set_trace_context(Some(next_hex(32)), Some(next_hex(16)));
    callback()
}
