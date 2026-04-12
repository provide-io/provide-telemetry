// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// Regression tests for the no-governance build (`--no-default-features`).
// These tests run only when governance is absent and assert that core
// telemetry features work correctly without the governance modules.
#![cfg(not(feature = "governance"))]

use provide_telemetry::{
    counter, get_health_snapshot, get_logger, replace_pii_rules, sanitize_payload, setup_telemetry,
    shutdown_telemetry, PIIMode, PIIRule,
};
use serde_json::json;

/// Core setup/shutdown lifecycle works without governance.
#[test]
fn no_governance_setup_shutdown_roundtrip() {
    let _ = shutdown_telemetry();
    let cfg = setup_telemetry().expect("setup must succeed without governance");
    assert!(
        !cfg.service_name.is_empty(),
        "config must include a service name"
    );
    let _ = shutdown_telemetry();
}

/// Logger is available and usable without governance.
#[test]
fn no_governance_logger_usable() {
    let logger = get_logger(None);
    logger.info("no_governance.test.logged");
}

/// PII redaction works without governance: sensitive keys are masked,
/// no classification labels are injected, no receipts are emitted.
#[test]
fn no_governance_pii_sanitize_redacts_sensitive_keys() {
    replace_pii_rules(vec![]);
    let payload = json!({
        "user": "alice",
        "password": "s3cr3t",  // pragma: allowlist secret
        "token": "abc123",
        "email": "alice@example.com"
    });
    let result = sanitize_payload(&payload, true, 3);
    assert_eq!(result["password"], "***", "password must be redacted");
    assert_eq!(result["token"], "***", "token must be redacted");
    assert_eq!(
        result["user"], "alice",
        "non-sensitive key must pass through"
    );
    // No __password__class annotation without governance
    assert!(
        result.get("__password__class").is_none(),
        "classification labels must be absent without governance"
    );
}

/// Explicit PII rules still apply without governance.
#[test]
fn no_governance_pii_rules_applied() {
    replace_pii_rules(vec![PIIRule::new(
        vec!["ssn".to_string()],
        PIIMode::Redact,
        8,
    )]);
    let payload = json!({ "ssn": "123-45-6789", "name": "alice" });
    let result = sanitize_payload(&payload, true, 3);
    assert_eq!(result["ssn"], "***", "explicit PIIRule must be applied");
    assert_eq!(result["name"], "alice", "non-rule field must pass through");
    replace_pii_rules(vec![]);
}

/// Health snapshot is available and has non-negative counters without governance.
#[test]
fn no_governance_health_snapshot_available() {
    let snap = get_health_snapshot();
    assert!(snap.emitted_logs >= 0);
    assert!(snap.dropped_logs >= 0);
    assert!(snap.emitted_traces >= 0);
    assert!(snap.emitted_metrics >= 0);
}

/// Counter instrument works without governance.
#[test]
fn no_governance_counter_usable() {
    let c = counter("no_governance.test.counter", None, None);
    c.add(1.0, None);
}
