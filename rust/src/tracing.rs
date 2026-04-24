// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;

use crate::context::trace_snapshot;
use crate::tracer::Tracer;

pub fn get_tracer(name: Option<&str>) -> Tracer {
    crate::tracer::get_tracer(name)
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
    crate::tracer::trace(name, callback)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testing::{acquire_test_state_lock, reset_trace_context};
    use crate::tracer::set_trace_context;

    #[test]
    fn tracing_test_tracer_names_match_contract() {
        assert_eq!(get_tracer(None).name(), "provide.telemetry");
        assert_eq!(get_tracer(Some("custom.tracer")).name(), "custom.tracer");
    }

    #[test]
    fn tracing_test_trace_invokes_callback() {
        let result = trace("test.span", || 42_i32);
        assert_eq!(result, 42);
    }

    #[test]
    fn tracing_test_get_trace_context_reflects_bound_snapshot() {
        let _guard = acquire_test_state_lock();
        reset_trace_context();

        let _ctx = set_trace_context(Some("a".repeat(32)), Some("b".repeat(16)));
        let snapshot = get_trace_context();

        assert_eq!(snapshot.get("trace_id"), Some(&Some("a".repeat(32))));
        assert_eq!(snapshot.get("span_id"), Some(&Some("b".repeat(16))));
    }
}
