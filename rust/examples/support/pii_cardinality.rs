// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use provide_telemetry::{
    clear_cardinality_limits, get_cardinality_limits, get_pii_rules, register_cardinality_limit,
    register_pii_rule, replace_pii_rules, sanitize_payload, CardinalityLimit, PIIMode, PIIRule,
    TelemetryError,
};
use serde_json::json;

#[derive(Debug, Clone, PartialEq)]
pub struct DemoSummary {
    pub hashed_email_len: usize,
    pub credit_card_removed: bool,
    pub truncated_password: Option<String>,
    pub cardinality_max_values: Option<usize>,
    pub cardinality_ttl_seconds: Option<f64>,
    pub pii_rule_count: usize,
}

pub fn run_demo() -> Result<DemoSummary, TelemetryError> {
    replace_pii_rules(Vec::new());
    clear_cardinality_limits();

    register_pii_rule(PIIRule::new(
        vec!["user".to_string(), "email".to_string()],
        PIIMode::Hash,
        0,
    ));
    register_pii_rule(PIIRule::new(
        vec!["credit_card".to_string()],
        PIIMode::Drop,
        0,
    ));
    register_pii_rule(PIIRule::new(
        vec!["password".to_string()],
        PIIMode::Truncate,
        4,
    ));

    let cleaned = sanitize_payload(
        &json!({
            "user": {"email": "dev@example.com"},
            "credit_card": "4111111111111111",
            "password": "hunter2" // pragma: allowlist secret
        }),
        true,
        8,
    );

    register_cardinality_limit(
        "user_id",
        CardinalityLimit {
            max_values: 0,
            ttl_seconds: 0.0,
        },
    );
    let limits = get_cardinality_limits();
    let user_limit = limits.get("user_id");

    Ok(DemoSummary {
        hashed_email_len: cleaned["user"]["email"].as_str().unwrap_or_default().len(),
        credit_card_removed: cleaned.get("credit_card").is_none(),
        truncated_password: cleaned["password"].as_str().map(str::to_string),
        cardinality_max_values: user_limit.map(|limit| limit.max_values),
        cardinality_ttl_seconds: user_limit.map(|limit| limit.ttl_seconds),
        pii_rule_count: get_pii_rules().len(),
    })
}
