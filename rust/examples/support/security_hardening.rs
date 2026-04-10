// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use provide_telemetry::{replace_pii_rules, sanitize_payload, TelemetryError};
use serde_json::json;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DemoSummary {
    pub secret_redacted: bool,
    pub password_redacted: bool,
    pub depth_preserved_leaf: Option<String>,
}

pub fn run_demo() -> Result<DemoSummary, TelemetryError> {
    replace_pii_rules(Vec::new());
    let cleaned = sanitize_payload(
        &json!({
            "user": "alice",
            "password": "hunter2", // pragma: allowlist secret
            "debug_output": "AKIAIOSFODNN7EXAMPLE", // pragma: allowlist secret
        }),
        true,
        8,
    );
    let deep = sanitize_payload(
        &json!({"l1": {"l2": {"l3": {"l4": {"l5": "deep"}}}}}),
        true,
        4,
    );
    Ok(DemoSummary {
        secret_redacted: cleaned["debug_output"].as_str() == Some("***"),
        password_redacted: cleaned["password"].as_str() == Some("***"),
        depth_preserved_leaf: deep["l1"]["l2"]["l3"]["l4"]["l5"]
            .as_str()
            .map(str::to_string),
    })
}
