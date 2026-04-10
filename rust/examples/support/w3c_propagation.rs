// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use provide_telemetry::{
    bind_propagation_context, extract_w3c_context, get_trace_context, setup_telemetry,
    shutdown_telemetry, TelemetryError,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DemoSummary {
    pub http_trace_id: Option<String>,
    pub manual_trace_id_after_clear: Option<String>,
    pub nested_outer_restored: Option<String>,
    pub nested_after_clear: Option<String>,
}

pub fn run_demo() -> Result<DemoSummary, TelemetryError> {
    let _ = shutdown_telemetry();
    setup_telemetry()?;

    let http = extract_w3c_context(
        Some("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"),
        Some("vendor=value"),
        Some("user_id=123"),
    );
    let http_trace_id = {
        let _guard = bind_propagation_context(http);
        get_trace_context().get("trace_id").and_then(Clone::clone)
    };

    let manual = extract_w3c_context(
        Some("00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"),
        Some("game=chess"),
        None,
    );
    let manual_trace_id_after_clear = {
        let _guard = bind_propagation_context(manual);
        drop(_guard);
        get_trace_context().get("trace_id").and_then(Clone::clone)
    };

    let outer = extract_w3c_context(
        Some("00-1111111111111111ffffffffffffffff-1111111111111111-01"),
        None,
        None,
    );
    let inner = extract_w3c_context(
        Some("00-2222222222222222ffffffffffffffff-2222222222222222-01"),
        None,
        None,
    );
    let outer_guard = bind_propagation_context(outer);
    let nested_outer_restored = {
        let _inner = bind_propagation_context(inner);
        drop(_inner);
        get_trace_context().get("trace_id").and_then(Clone::clone)
    };
    drop(outer_guard);
    let nested_after_clear = get_trace_context().get("trace_id").and_then(Clone::clone);

    shutdown_telemetry()?;
    Ok(DemoSummary {
        http_trace_id,
        manual_trace_id_after_clear,
        nested_outer_restored,
        nested_after_clear,
    })
}
