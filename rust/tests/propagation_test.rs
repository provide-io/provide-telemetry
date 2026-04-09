// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use provide_telemetry::{
    bind_context, bind_propagation_context, extract_w3c_context, get_trace_context,
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
fn propagation_test_bind_restores_previous_context_on_drop() {
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
        assert_eq!(
            active.get("trace_id").and_then(std::clone::Clone::clone),
            Some("4bf92f3577b34da6a3ce929d0e0e4736".to_string()) // pragma: allowlist secret
        );
    }

    let restored = get_trace_context();
    assert_eq!(
        restored.get("trace_id").and_then(std::clone::Clone::clone),
        Some("a".repeat(32))
    );
    drop(outer_trace);
}
