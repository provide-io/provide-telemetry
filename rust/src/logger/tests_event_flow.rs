// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

use super::*;

#[test]
fn new_event_injects_runtime_identity_context_and_trace() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();

    set_active_config(Some(TelemetryConfig {
        service_name: "svc".to_string(),
        environment: "stage".to_string(),
        version: "1.2.3".to_string(),
        ..TelemetryConfig::default()
    }));
    let _context = crate::context::bind_context([("request_id", json!("req-1"))]);
    let _trace = set_trace_context(
        Some("0123456789abcdef0123456789abcdef".to_string()), // pragma: allowlist secret
        Some("0123456789abcdef".to_string()),                 // pragma: allowlist secret
    );

    let event = new_event("tests.identity", "INFO", "identity.check");

    assert_eq!(event.target, "tests.identity");
    assert_eq!(event.level, "INFO");
    assert_eq!(event.message, "identity.check");
    assert_eq!(event.context.get("request_id"), Some(&json!("req-1")));
    assert_eq!(event.context.get("service"), Some(&json!("svc")));
    assert_eq!(event.context.get("env"), Some(&json!("stage")));
    assert_eq!(event.context.get("version"), Some(&json!("1.2.3")));
    assert_eq!(
        event.trace_id.as_deref(),
        Some("0123456789abcdef0123456789abcdef") // pragma: allowlist secret
    );
    assert_eq!(event.span_id.as_deref(), Some("0123456789abcdef")); // pragma: allowlist secret
    assert_eq!(event.event_metadata, None);
}

#[test]
fn new_event_skips_identity_when_runtime_and_env_config_are_unavailable() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    std::env::set_var("PROVIDE_LOG_PII_MAX_DEPTH", "-1");

    let event = new_event("tests.identity", "INFO", "identity.missing");

    assert_eq!(event.context.get("service"), None);
    assert_eq!(event.context.get("env"), None);
    assert_eq!(event.context.get("version"), None);

    std::env::remove_var("PROVIDE_LOG_PII_MAX_DEPTH");
}

#[test]
fn inject_runtime_identity_fields_is_a_noop_without_runtime_or_valid_env() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    std::env::set_var("PROVIDE_LOG_PII_MAX_DEPTH", "-1");

    let mut context = BTreeMap::new();
    inject_runtime_identity_fields(&mut context);

    assert!(context.is_empty());
    std::env::remove_var("PROVIDE_LOG_PII_MAX_DEPTH");
}

#[test]
fn log_event_helpers_cover_threshold_fields_and_event_metadata() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    configure_logging(crate::config::LoggingConfig {
        level: "INFO".to_string(),
        ..trace_json_config()
    });
    enable_test_capture();

    let before = crate::health::get_health_snapshot();
    log_event("DEBUG", "tests.filtered", "filtered.out");
    assert!(Logger::drain_events_for_tests().is_empty());
    assert_eq!(
        crate::health::get_health_snapshot().emitted_logs,
        before.emitted_logs
    );

    configure_logging(crate::config::LoggingConfig {
        level: "INFO".to_string(),
        ..trace_json_config()
    });
    let mut extra = BTreeMap::new();
    extra.insert("step".to_string(), json!("parse"));
    log_event_with_fields("INFO", "tests.fields", "fields.ok", &extra);

    let ev = event(&["auth", "login", "success"]).expect("event should build");
    log_event_with_event("ERROR", "tests.event", &ev);

    let events = Logger::drain_events_for_tests();
    assert_eq!(events.len(), 2);
    assert_eq!(events[0].context.get("step"), Some(&json!("parse")));
    assert_eq!(
        events[1].event_metadata,
        Some(EventMetadata {
            domain: "auth".to_string(),
            action: "login".to_string(),
            resource: None,
            status: "success".to_string(),
        })
    );
}

#[test]
fn log_event_helpers_respect_consent_gate() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    configure_logging(trace_json_config());
    enable_test_capture();
    set_consent_level(ConsentLevel::None);
    let before = crate::health::get_health_snapshot();

    log_event("ERROR", "tests.consent", "blocked.by.consent");
    log_event_with_fields("ERROR", "tests.consent", "blocked.fields", &BTreeMap::new());
    let ev = event(&["auth", "login", "denied"]).expect("event should build");
    log_event_with_event("ERROR", "tests.consent", &ev);

    assert!(Logger::drain_events_for_tests().is_empty());
    // Each refusal is a drop, as the health snapshot spec names consent.
    let after = crate::health::get_health_snapshot();
    assert_eq!(after.emitted_logs, before.emitted_logs);
    assert_eq!(after.dropped_logs, before.dropped_logs + 3);
}

#[test]
fn stamped_root_fields_replace_caller_fields_and_unstamped_ones_leave_them() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();
    let mut forged = BTreeMap::new();
    for key in ["service", "env", "version", "trace_id", "span_id"] {
        forged.insert(key.to_string(), json!(format!("forged-{key}")));
    }

    set_active_config(Some(TelemetryConfig {
        service_name: "svc".to_string(),
        environment: "stage".to_string(),
        version: "1.2.3".to_string(),
        ..TelemetryConfig::default()
    }));
    let _context = crate::context::bind_context([("env", json!("bound-env"))]);
    let trace = set_trace_context(
        Some("0123456789abcdef0123456789abcdef".to_string()), // pragma: allowlist secret
        Some("0123456789abcdef".to_string()),                 // pragma: allowlist secret
    );
    let stamped = build_event("tests.identity", "INFO", "identity.forged", &forged);
    assert_eq!(stamped.context.get("service"), Some(&json!("svc")));
    assert_eq!(stamped.context.get("env"), Some(&json!("stage")));
    assert_eq!(stamped.context.get("version"), Some(&json!("1.2.3")));
    // The live context is rendered over the map; the forged keys are gone
    // rather than left for the OTel bridge to forward as attributes.
    assert_eq!(stamped.context.get("trace_id"), None);
    assert_eq!(stamped.context.get("span_id"), None);
    assert_eq!(
        stamped.trace_id.as_deref(),
        Some("0123456789abcdef0123456789abcdef") // pragma: allowlist secret
    );
    drop(trace);

    // Nothing stamped: no live span, an empty identity. The caller's stand.
    set_active_config(Some(TelemetryConfig {
        service_name: String::new(),
        environment: String::new(),
        version: String::new(),
        ..TelemetryConfig::default()
    }));
    let _cleared = set_trace_context(None, None);
    let unstamped = build_event("tests.identity", "INFO", "identity.kept", &forged);
    for key in ["service", "env", "version", "trace_id", "span_id"] {
        assert_eq!(
            unstamped.context.get(key),
            Some(&json!(format!("forged-{key}"))),
            "{key}"
        );
    }
    assert_eq!(unstamped.trace_id, None);
}
