use super::*;

use crate::runtime::set_active_config;
use crate::testing::acquire_test_state_lock;
use crate::{EventMetadata, EventSchemaConfig, TelemetryConfig};
use std::collections::BTreeMap;

fn make_event(level: &str, message: &str) -> LogEvent {
    LogEvent {
        level: level.to_string(),
        target: "test".to_string(),
        message: message.to_string(),
        context: BTreeMap::new(),
        trace_id: None,
        span_id: None,
        event_metadata: None,
    }
}

#[test]
fn extract_dars_fields_includes_resource_when_present() {
    let mut event = make_event("INFO", "orders.create.ok");
    event.event_metadata = Some(EventMetadata {
        domain: "orders".to_string(),
        action: "create".to_string(),
        resource: Some("invoice".to_string()),
        status: "ok".to_string(),
    });

    extract_dars_fields(&mut event);

    assert_eq!(
        event.context.get("domain"),
        Some(&Value::String("orders".into()))
    );
    assert_eq!(
        event.context.get("action"),
        Some(&Value::String("create".into()))
    );
    assert_eq!(
        event.context.get("resource"),
        Some(&Value::String("invoice".into()))
    );
    assert_eq!(
        event.context.get("status"),
        Some(&Value::String("ok".into()))
    );
}

#[test]
fn sanitize_context_returns_early_for_empty_context() {
    let mut event = make_event("INFO", "clean.message");
    sanitize_context(&mut event, 8);
    assert_eq!(event.message, "clean.message");
    assert!(event.context.is_empty());
}

#[test]
fn enforce_schema_prefers_runtime_required_key_errors() {
    let _guard = acquire_test_state_lock();
    crate::testing::reset_telemetry_state();
    set_active_config(Some(TelemetryConfig {
        event_schema: EventSchemaConfig {
            required_keys: vec!["request_id".to_string()],
            ..EventSchemaConfig::default()
        },
        strict_schema: true,
        ..TelemetryConfig::default()
    }));

    let mut event = make_event("INFO", "auth.login.ok");
    enforce_schema(&mut event);

    let schema_error = event
        .context
        .get("_schema_error")
        .and_then(Value::as_str)
        .expect("missing required key should be reported");
    assert!(schema_error.contains("request_id"));

    set_active_config(None);
}
