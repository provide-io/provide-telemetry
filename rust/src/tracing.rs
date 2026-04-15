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
}
