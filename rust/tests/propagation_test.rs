// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use provide_telemetry::testing::acquire_test_state_lock;
use provide_telemetry::{
    bind_context, bind_propagation_context, extract_w3c_context, get_trace_context, parse_baggage,
};
use rstest::rstest;
use serde_json::json;

#[rstest]
#[case(Some("x".repeat(513)), Some("k=v".to_string()), Some("a=b".to_string()))]
#[case(Some("00-zzzz-zzzz-01".to_string()), Some("k=v".to_string()), None)]
fn propagation_test_invalid_traceparent_is_discarded(
    #[case] traceparent: Option<String>,
    #[case] tracestate: Option<String>,
    #[case] baggage: Option<String>,
) {
    let _guard = acquire_test_state_lock();
    let context = extract_w3c_context(
        traceparent.as_deref(),
        tracestate.as_deref(),
        baggage.as_deref(),
    );

    assert!(context.traceparent.is_none());
    assert!(context.trace_id.is_none());
    assert!(context.span_id.is_none());
    assert_eq!(context.tracestate.as_deref(), tracestate.as_deref());
}

#[test]
fn propagation_test_tracestate_over_32_pairs_is_discarded() {
    let _guard = acquire_test_state_lock();
    let pairs = (0..33)
        .map(|index| format!("k{index}=v{index}"))
        .collect::<Vec<_>>()
        .join(",");
    let traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";
    let context = extract_w3c_context(Some(traceparent), Some(&pairs), None);

    assert_eq!(context.traceparent.as_deref(), Some(traceparent));
    assert!(context.tracestate.is_none());
    assert_eq!(
        context.trace_id.as_deref(),
        Some("4bf92f3577b34da6a3ce929d0e0e4736") // pragma: allowlist secret
    );
}

#[test]
fn propagation_test_exact_header_limits_are_preserved() {
    let _guard = acquire_test_state_lock();
    let exact_traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";
    let exact_tracestate = (0..32)
        .map(|index| format!("k{index}=v{index}"))
        .collect::<Vec<_>>()
        .join(",");
    let exact_baggage = "a".repeat(8192);

    let context = extract_w3c_context(
        Some(exact_traceparent),
        Some(&exact_tracestate),
        Some(&exact_baggage),
    );

    assert_eq!(context.traceparent.as_deref(), Some(exact_traceparent));
    assert_eq!(
        context.tracestate.as_deref(),
        Some(exact_tracestate.as_str())
    );
    assert_eq!(context.baggage.as_deref(), Some(exact_baggage.as_str()));
}

#[rstest]
#[case("ff-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")]
#[case("00-00000000000000000000000000000000-00f067aa0ba902b7-01")]
#[case("00-4bf92f3577b34da6a3ce929d0e0e4736-0000000000000000-01")]
#[case("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-0z")]
fn propagation_test_traceparent_validation_rejects_each_invalid_component(
    #[case] traceparent: &str,
) {
    let _guard = acquire_test_state_lock();
    let context = extract_w3c_context(Some(traceparent), Some("k=v"), Some("a=b"));

    assert!(context.traceparent.is_none());
    assert!(context.trace_id.is_none());
    assert!(context.span_id.is_none());
    assert_eq!(context.tracestate.as_deref(), Some("k=v"));
    assert_eq!(context.baggage.as_deref(), Some("a=b"));
}

#[test]
fn propagation_test_bind_restores_previous_context_on_drop() {
    let _guard = acquire_test_state_lock();
    let _outer = bind_context([("request_id".to_string(), json!("req-1"))]);
    let outer_trace =
        provide_telemetry::set_trace_context(Some("a".repeat(32)), Some("b".repeat(16))); // pragma: allowlist secret

    let context = extract_w3c_context(
        Some("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"),
        Some("k=v"),
        Some("a=b"),
    );

    {
        let _guard = bind_propagation_context(context);
        let active = get_trace_context();
        let active_context = provide_telemetry::context::get_context();
        assert_eq!(
            active.get("trace_id").and_then(std::clone::Clone::clone),
            Some("4bf92f3577b34da6a3ce929d0e0e4736".to_string()) // pragma: allowlist secret
        );
        assert_eq!(
            active_context.get("traceparent"),
            Some(&json!(
                "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
            ))
        );
        assert_eq!(active_context.get("tracestate"), Some(&json!("k=v")));
        assert_eq!(active_context.get("baggage"), Some(&json!("a=b")));
    }

    let restored = get_trace_context();
    let restored_context = provide_telemetry::context::get_context();
    assert_eq!(
        restored.get("trace_id").and_then(std::clone::Clone::clone),
        Some("a".repeat(32))
    );
    assert_eq!(restored_context.get("request_id"), Some(&json!("req-1")));
    assert!(!restored_context.contains_key("traceparent"));
    assert!(!restored_context.contains_key("tracestate"));
    assert!(!restored_context.contains_key("baggage"));
    drop(outer_trace);
}

#[test]
fn propagation_test_parse_baggage_simple() {
    let result = parse_baggage("key1=value1,key2=value2");
    assert_eq!(result.get("key1").map(String::as_str), Some("value1"));
    assert_eq!(result.get("key2").map(String::as_str), Some("value2"));
    assert_eq!(result.len(), 2);
}

#[test]
fn propagation_test_parse_baggage_strips_properties_after_semicolon() {
    let result = parse_baggage("key1=value1;prop=x,key2=value2;ttl=100");
    assert_eq!(result.get("key1").map(String::as_str), Some("value1"));
    assert_eq!(result.get("key2").map(String::as_str), Some("value2"));
    assert_eq!(result.len(), 2);
}

#[test]
fn propagation_test_parse_baggage_skips_member_with_no_equals() {
    let result = parse_baggage("noequals,key=value");
    assert!(!result.contains_key("noequals"));
    assert_eq!(result.get("key").map(String::as_str), Some("value"));
    assert_eq!(result.len(), 1);
}

#[test]
fn propagation_test_parse_baggage_skips_empty_key() {
    let result = parse_baggage("=value,key=val");
    assert!(!result.contains_key(""));
    assert_eq!(result.get("key").map(String::as_str), Some("val"));
    assert_eq!(result.len(), 1);
}

#[test]
fn propagation_test_parse_baggage_empty_string() {
    let result = parse_baggage("");
    assert!(result.is_empty());
}

#[test]
fn propagation_test_bind_injects_parsed_baggage_entries() {
    let _guard = acquire_test_state_lock();
    let context = extract_w3c_context(None, None, Some("user=alice,env=prod"));

    {
        let _guard = bind_propagation_context(context);
        let active_context = provide_telemetry::context::get_context();
        assert_eq!(
            active_context.get("baggage.user"),
            Some(&serde_json::json!("alice"))
        );
        assert_eq!(
            active_context.get("baggage.env"),
            Some(&serde_json::json!("prod"))
        );
        assert_eq!(
            active_context.get("baggage"),
            Some(&serde_json::json!("user=alice,env=prod"))
        );
    }

    let restored = provide_telemetry::context::get_context();
    assert!(!restored.contains_key("baggage"));
    assert!(!restored.contains_key("baggage.user"));
    assert!(!restored.contains_key("baggage.env"));
}

#[test]
fn propagation_test_bind_sets_trace_context_when_only_trace_id_is_present() {
    let _guard = acquire_test_state_lock();
    let context = provide_telemetry::PropagationContext {
        traceparent: None,
        tracestate: None,
        baggage: None,
        trace_id: Some("c".repeat(32)),
        span_id: None,
    };

    {
        let _guard = bind_propagation_context(context);
        let active = get_trace_context();
        assert_eq!(
            active.get("trace_id").and_then(std::clone::Clone::clone),
            Some("c".repeat(32))
        );
        assert_eq!(
            active.get("span_id").and_then(std::clone::Clone::clone),
            None
        );
    }

    let restored = get_trace_context();
    assert_eq!(restored.get("trace_id"), Some(&None));
    assert_eq!(restored.get("span_id"), Some(&None));
}
