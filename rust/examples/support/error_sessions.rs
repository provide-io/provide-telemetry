// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use provide_telemetry::{
    bind_session_context, compute_error_fingerprint, get_session_id, setup_telemetry,
    shutdown_telemetry, TelemetryError,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DemoSummary {
    pub value_error_a: String,
    pub value_error_b: String,
    pub type_error: String,
    pub runtime_error_fingerprint: String,
    pub session_before: Option<String>,
    pub session_after_bind: Option<String>,
    pub session_after_clear: Option<String>,
}

pub fn run_demo() -> Result<DemoSummary, TelemetryError> {
    let _ = shutdown_telemetry();
    setup_telemetry()?;
    let value_error_a = compute_error_fingerprint("ValueError", None);
    let value_error_b = compute_error_fingerprint("ValueError", None);
    let type_error = compute_error_fingerprint("TypeError", None);
    let runtime_error_fingerprint = compute_error_fingerprint(
        "RuntimeError",
        Some("at demo_runtime (examples/error_sessions.rs:24:1)"),
    );
    let session_before = get_session_id();
    let guard = bind_session_context("sess-demo-42");
    let session_after_bind = get_session_id();
    drop(guard);
    let session_after_clear = get_session_id();
    shutdown_telemetry()?;
    Ok(DemoSummary {
        value_error_a,
        value_error_b,
        type_error,
        runtime_error_fingerprint,
        session_before,
        session_after_bind,
        session_after_clear,
    })
}
