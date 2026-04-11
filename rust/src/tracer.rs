// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;
use std::sync::atomic::{AtomicU64, Ordering};

use crate::context::{set_trace_context_internal, trace_snapshot, ContextGuard};

pub struct NoopSpan {
    trace_id: String,
    span_id: String,
    guard: Option<ContextGuard>,
}

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

    pub fn start_span(&self, _name: &str) -> NoopSpan {
        let trace_id = next_hex(32);
        let span_id = next_hex(16);
        let guard = set_trace_context(Some(trace_id.clone()), Some(span_id.clone()));
        NoopSpan {
            trace_id,
            span_id,
            guard: Some(guard),
        }
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
    let _span = tracer.start_span(name);
    callback()
}

impl NoopSpan {
    pub fn trace_id(&self) -> &str {
        &self.trace_id
    }

    pub fn span_id(&self) -> &str {
        &self.span_id
    }

    pub fn set_attribute(&self, _key: &str, _value: &str) {}

    pub fn record_error(&self, _error: &str) {}
}

impl Drop for NoopSpan {
    fn drop(&mut self) {
        drop(self.guard.take());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tracer_test_tracer_names_match_contract() {
        assert_eq!(tracer.name(), "provide.telemetry");
        assert_eq!(get_tracer(Some("custom.tracer")).name(), "custom.tracer");
    }

    #[test]
    fn tracer_test_next_hex_respects_requested_length_and_advances() {
        let first = next_hex(16);
        let second = next_hex(16);
        let long = next_hex(32);

        assert_eq!(first.len(), 16);
        assert_eq!(second.len(), 16);
        assert_eq!(long.len(), 32);
        assert_ne!(first, second);
        assert!(first.chars().all(|ch| ch.is_ascii_hexdigit()));
        assert!(long.chars().all(|ch| ch.is_ascii_hexdigit()));
    }
}
