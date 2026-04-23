use super::*;
use crate::TelemetryConfig;
use crate::runtime::set_active_config;
use crate::setup::{setup_telemetry, shutdown_telemetry};
use crate::testing::acquire_test_state_lock;
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
fn harden_input_truncates_long_values() {
    let mut event = make_event("INFO", "test");
    event
        .context
        .insert("long".to_string(), Value::String("x".repeat(2000)));
    harden_input(&mut event, 100, 64);
    let val = event.context["long"].as_str().unwrap();
    assert!(val.len() <= 103, "value should be truncated + '...'");
    assert!(val.ends_with("..."));
}

#[test]
fn harden_input_truncates_safely_on_multibyte_utf8() {
    let mut event = make_event("INFO", "test");
    event
        .context
        .insert("multi".to_string(), Value::String("ééééé".to_string()));
    harden_input(&mut event, 5, 64);
    let val = event.context["multi"].as_str().unwrap();
    assert!(val.is_char_boundary(val.len()), "must end at char boundary");
    assert!(val.ends_with("..."));
}

#[test]
fn truncate_string_value_handles_first_multibyte_char_exceeding_limit() {
    let mut value = "éé".to_string();
    truncate_string_value(&mut value, 1);
    assert_eq!(value, "...");
}

#[test]
fn harden_input_strips_control_chars() {
    let mut event = make_event("INFO", "test");
    event.context.insert(
        "dirty".to_string(),
        Value::String("hello\x00world\ttab\n".to_string()),
    );
    harden_input(&mut event, 1024, 64);
    assert_eq!(
        event.context["dirty"].as_str().unwrap(),
        "helloworld\ttab\n"
    );
}

#[test]
fn harden_input_caps_attr_count() {
    let mut event = make_event("INFO", "test");
    for i in 0..20 {
        event
            .context
            .insert(format!("key_{i:02}"), Value::String(format!("val_{i}")));
    }
    harden_input(&mut event, 1024, 5);
    assert_eq!(event.context.len(), 5, "should cap at 5 attributes");
}

#[test]
fn harden_input_preserves_priority_keys_when_over_cap() {
    let mut event = make_event("INFO", "test");
    for i in 0..10 {
        event
            .context
            .insert(format!("extra_{i:02}"), Value::String("x".to_string()));
    }
    event
        .context
        .insert("trace_id".to_string(), Value::String("tid-abc".to_string()));
    event
        .context
        .insert("service".to_string(), Value::String("svc".to_string()));
    harden_input(&mut event, 1024, 4);
    assert_eq!(event.context.len(), 4, "must cap at 4");
    assert!(
        event.context.contains_key("trace_id"),
        "trace_id (priority) must survive capping"
    );
    assert!(
        event.context.contains_key("service"),
        "service (priority) must survive capping"
    );
}

#[test]
fn error_fingerprint_added_when_error_attr_present() {
    let mut event = make_event("ERROR", "something failed");
    event
        .context
        .insert("error".to_string(), Value::String("ValueError".to_string()));
    add_error_fingerprint(&mut event);
    let fp = event
        .context
        .get("error_fingerprint")
        .unwrap()
        .as_str()
        .unwrap();
    assert_eq!(fp.len(), 12, "fingerprint should be 12 hex chars");
    assert!(fp.chars().all(|c| c.is_ascii_hexdigit()));
}

#[test]
fn error_fingerprint_not_added_without_error_attr() {
    let mut event = make_event("ERROR", "plain error message");
    add_error_fingerprint(&mut event);
    assert!(
        !event.context.contains_key("error_fingerprint"),
        "fingerprint requires error attrs in context"
    );
}

#[test]
fn error_fingerprint_not_added_for_info_events() {
    let mut event = make_event("INFO", "normal log");
    event
        .context
        .insert("error".to_string(), Value::String("SomeError".to_string()));
    add_error_fingerprint(&mut event);
    assert!(!event.context.contains_key("error_fingerprint"));
}

#[test]
fn sanitize_context_redacts_sensitive_keys() {
    let mut event = make_event("INFO", "test");
    event
        .context
        .insert("password".to_string(), Value::String("s3cret".to_string()));
    event
        .context
        .insert("safe_key".to_string(), Value::String("visible".to_string()));
    sanitize_context(&mut event, 8);
    assert_ne!(
        event.context["password"].as_str().unwrap(),
        "s3cret",
        "password should be redacted"
    );
    assert_eq!(event.context["safe_key"].as_str().unwrap(), "visible");
}

#[test]
fn enforce_schema_adds_error_field_for_invalid_name_in_strict_mode() {
    let _guard = acquire_test_state_lock();
    crate::schema::set_strict_schema(true);
    let mut event = make_event("INFO", "NOT-VALID.name");
    enforce_schema(&mut event);
    assert!(
        event.context.contains_key("_schema_error"),
        "strict mode should flag invalid name"
    );
    crate::schema::set_strict_schema(false);
}

#[test]
fn enforce_schema_passes_valid_name_in_strict_mode() {
    let _guard = acquire_test_state_lock();
    crate::schema::set_strict_schema(true);
    let mut event = make_event("INFO", "auth.login.ok");
    enforce_schema(&mut event);
    assert!(
        !event.context.contains_key("_schema_error"),
        "valid name should not be flagged"
    );
    crate::schema::set_strict_schema(false);
}

#[test]
fn inject_logger_name_sets_target_as_logger_name() {
    let mut event = make_event("INFO", "auth.login.ok");
    event.target = "myapp.auth".to_string();
    inject_logger_name(&mut event);
    assert_eq!(
        event.context.get("logger_name").and_then(|v| v.as_str()),
        Some("myapp.auth"),
        "target should be injected as logger_name"
    );
}

#[test]
fn inject_logger_name_does_not_overwrite_caller_provided_value() {
    let mut event = make_event("INFO", "auth.login.ok");
    event.target = "myapp.auth".to_string();
    event.context.insert(
        "logger_name".to_string(),
        Value::String("explicit".to_string()),
    );
    inject_logger_name(&mut event);
    assert_eq!(
        event.context.get("logger_name").and_then(|v| v.as_str()),
        Some("explicit"),
        "caller-set logger_name must not be overwritten"
    );
}

#[test]
fn inject_logger_name_skips_empty_target() {
    let mut event = make_event("INFO", "auth.login.ok");
    event.target = String::new();
    inject_logger_name(&mut event);
    assert!(
        !event.context.contains_key("logger_name"),
        "empty target must not inject logger_name"
    );
}

#[test]
fn harden_input_preserves_logger_name_as_priority_key() {
    let mut event = make_event("INFO", "test");
    for i in 0..10 {
        event
            .context
            .insert(format!("extra_{i:02}"), Value::String("x".to_string()));
    }
    event.context.insert(
        "logger_name".to_string(),
        Value::String("my.logger".to_string()),
    );
    harden_input(&mut event, 1024, 3);
    assert!(
        event.context.contains_key("logger_name"),
        "logger_name must survive attribute capping as a priority key"
    );
}

#[test]
fn harden_input_handles_empty_and_non_string_values() {
    let mut event = make_event("INFO", "test");
    harden_input(&mut event, 16, 4);
    assert!(event.context.is_empty());

    event.context.insert(
        "count".to_string(),
        Value::Number(serde_json::Number::from(7)),
    );
    harden_input(&mut event, 16, 4);
    assert_eq!(event.context.get("count"), Some(&Value::Number(7.into())));
}

#[test]
fn harden_input_zero_attr_limit_disables_capping() {
    let mut event = make_event("INFO", "test");
    for idx in 0..6 {
        event.context.insert(
            format!("field_{idx}"),
            Value::String(format!("value_{idx}")),
        );
    }

    harden_input(&mut event, 16, 0);

    assert_eq!(event.context.len(), 6);
}

#[test]
fn harden_input_skips_priority_keys_encountered_after_non_priority_fill() {
    let mut event = make_event("INFO", "test");
    event
        .context
        .insert("alpha".to_string(), Value::String("a".to_string()));
    event
        .context
        .insert("beta".to_string(), Value::String("b".to_string()));
    event.context.insert(
        "trace_id".to_string(),
        Value::String("trace-123".to_string()),
    );
    event
        .context
        .insert("span_id".to_string(), Value::String("span-123".to_string()));

    harden_input(&mut event, 1024, 4);

    assert!(event.context.contains_key("trace_id"));
    assert!(event.context.contains_key("span_id"));
}

#[test]
fn harden_input_skips_priority_keys_during_non_priority_fill_before_limit() {
    let mut event = make_event("INFO", "test");
    event
        .context
        .insert("alpha".to_string(), Value::String("a".to_string()));
    event.context.insert(
        "logger_name".to_string(),
        Value::String("logger.test".to_string()),
    );
    event
        .context
        .insert("zeta".to_string(), Value::String("z".to_string()));
    event
        .context
        .insert("zz".to_string(), Value::String("zz".to_string()));

    harden_input(&mut event, 1024, 3);

    assert!(event.context.contains_key("logger_name"));
    assert!(event.context.contains_key("alpha"));
    assert!(event.context.contains_key("zeta"));
}

#[test]
fn add_error_fingerprint_uses_error_type_and_stacktrace_fallbacks() {
    let mut event = make_event("ERROR", "test");
    event.context.insert(
        "error_type".to_string(),
        Value::String("FallbackError".to_string()),
    );
    event.context.insert(
        "stacktrace".to_string(),
        Value::String("stacktrace line".to_string()),
    );

    add_error_fingerprint(&mut event);

    assert!(event.context.contains_key("error_fingerprint"));
}

#[test]
fn add_error_fingerprint_uses_exception_and_stack_fallbacks() {
    let mut event = make_event("ERROR", "test");
    event.context.insert(
        "exception".to_string(),
        Value::String("OtherError".to_string()),
    );
    event
        .context
        .insert("stack".to_string(), Value::String("stack line".to_string()));

    add_error_fingerprint(&mut event);

    assert!(event.context.contains_key("error_fingerprint"));
}

#[test]
fn add_error_fingerprint_accepts_critical_and_fatal_levels() {
    let mut critical = make_event("CRITICAL", "test");
    critical.context.insert(
        "error".to_string(),
        Value::String("CriticalError".to_string()),
    );
    add_error_fingerprint(&mut critical);
    assert!(critical.context.contains_key("error_fingerprint"));

    let mut fatal = make_event("FATAL", "test");
    fatal
        .context
        .insert("error".to_string(), Value::String("FatalError".to_string()));
    add_error_fingerprint(&mut fatal);
    assert!(fatal.context.contains_key("error_fingerprint"));
}

#[test]
fn add_error_fingerprint_ignores_non_string_error_values() {
    let mut event = make_event("ERROR", "test");
    event.context.insert(
        "error".to_string(),
        Value::Number(serde_json::Number::from(500)),
    );

    add_error_fingerprint(&mut event);

    assert!(!event.context.contains_key("error_fingerprint"));
}

#[test]
fn first_context_string_skips_missing_and_non_string_values() {
    let mut event = make_event("ERROR", "test");
    event.context.insert(
        "error".to_string(),
        Value::Number(serde_json::Number::from(500)),
    );
    event.context.insert(
        "exception".to_string(),
        Value::String("TypedError".to_string()),
    );

    assert_eq!(
        first_context_string(&event, &["missing", "error", "exception"]),
        Some("TypedError")
    );
    assert_eq!(first_context_string(&event, &["missing", "error"]), None);
}

#[test]
fn first_context_string_returns_none_for_empty_key_list() {
    let event = make_event("INFO", "test");
    assert_eq!(first_context_string(&event, &[]), None);
}

#[test]
fn runtime_schema_error_returns_none_without_runtime_and_message_with_runtime() {
    let _guard = acquire_test_state_lock();
    crate::testing::reset_telemetry_state();
    set_active_config(None);

    let event = make_event("INFO", "auth.login.ok");
    assert_eq!(runtime_schema_error(&event), None);

    set_active_config(Some(TelemetryConfig {
        event_schema: crate::EventSchemaConfig {
            required_keys: vec!["request_id".to_string()],
            ..crate::EventSchemaConfig::default()
        },
        ..TelemetryConfig::default()
    }));

    let schema_error =
        runtime_schema_error(&event).expect("missing required key must produce schema error");
    assert!(schema_error.contains("request_id"));

    set_active_config(None);
}

#[test]
fn truncate_and_strip_context_helpers_skip_empty_context() {
    let mut event = make_event("INFO", "test");
    truncate_context_values(&mut event, 8);
    strip_context_values(&mut event);
    assert!(event.context.is_empty());
}

#[test]
fn process_event_prefers_runtime_config_when_present() {
    let _guard = acquire_test_state_lock();
    crate::testing::reset_telemetry_state();
    shutdown_telemetry().expect("pre-test shutdown should succeed");

    std::env::set_var("PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH", "8");
    setup_telemetry().expect("setup should succeed");

    let mut event = make_event("INFO", "auth.login.ok");
    event.context.insert(
        "payload".to_string(),
        Value::String("abcdefghijklmnopqrstuvwxyz".to_string()),
    );
    process_event(&mut event);

    assert_eq!(
        event
            .context
            .get("payload")
            .and_then(|value| value.as_str()),
        Some("abcdefgh...")
    );

    shutdown_telemetry().expect("shutdown should succeed");
    std::env::remove_var("PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH");
}

#[test]
fn process_event_reads_env_config_when_runtime_is_absent() {
    let _guard = acquire_test_state_lock();
    crate::testing::reset_telemetry_state();
    shutdown_telemetry().expect("pre-test shutdown should succeed");

    std::env::set_var("PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH", "8");

    let mut event = make_event("INFO", "auth.login.ok");
    event.context.insert(
        "payload".to_string(),
        Value::String("abcdefghijklmnopqrstuvwxyz".to_string()),
    );
    process_event(&mut event);

    assert_eq!(
        event
            .context
            .get("payload")
            .and_then(|value| value.as_str()),
        Some("abcdefgh...")
    );

    std::env::remove_var("PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH");
}
