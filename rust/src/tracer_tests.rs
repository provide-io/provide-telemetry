use super::*;
use std::collections::BTreeMap;

use crate::backpressure::{_reset_backpressure_for_tests, set_queue_policy, QueuePolicy};
use crate::health::get_health_snapshot;
use crate::sampling::{_reset_sampling_for_tests, set_sampling_policy, SamplingPolicy};
use crate::testing::{acquire_test_state_lock, reset_telemetry_state, reset_trace_context};

#[test]
fn tracer_test_tracer_names_match_contract() {
    assert_eq!(tracer.name(), "provide.telemetry");
    assert_eq!(get_tracer(Some("custom.tracer")).name(), "custom.tracer");
}

#[test]
fn tracer_test_next_hex_respects_requested_length_and_advances() {
    let first = next_hex(16);
    let second = next_hex(16);
    let long = next_hex(32);
    let (long_left, long_right) = long.split_at(16);

    assert_eq!(first.len(), 16);
    assert_eq!(second.len(), 16);
    assert_eq!(long.len(), 32);
    assert_ne!(first, second);
    assert!(u64::from_str_radix(&first, 16).is_ok());
    assert!(u64::from_str_radix(long_left, 16).is_ok());
    assert!(u64::from_str_radix(long_right, 16).is_ok());
}

#[test]
fn tracer_test_start_span_sets_trace_context_and_restores_on_drop() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    let test_tracer = get_tracer(Some("unit.test"));
    let span = test_tracer.start_span("work.span");
    let active = get_trace_context();

    assert_eq!(span.trace_id().len(), 32);
    assert_eq!(span.span_id().len(), 16);
    assert_eq!(
        active.get("trace_id"),
        Some(&Some(span.trace_id().to_string()))
    );
    assert_eq!(
        active.get("span_id"),
        Some(&Some(span.span_id().to_string()))
    );

    span.set_attribute("kind", "internal");
    span.record_error("boom");
    drop(span);

    let cleared = get_trace_context();
    assert_eq!(cleared.get("trace_id"), Some(&None));
    assert_eq!(cleared.get("span_id"), Some(&None));
}

#[test]
fn tracer_test_trace_sets_context_inside_callback_and_emits() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    let before = get_health_snapshot().emitted_traces;
    let result = trace("unit.trace", || {
        let active = get_trace_context();
        assert!(active.get("trace_id").and_then(|v| v.as_ref()).is_some());
        assert!(active.get("span_id").and_then(|v| v.as_ref()).is_some());
        7_u32
    });

    assert_eq!(result, 7);
    assert_eq!(get_health_snapshot().emitted_traces, before + 1);
    let cleared = get_trace_context();
    assert_eq!(cleared.get("trace_id"), Some(&None));
    assert_eq!(cleared.get("span_id"), Some(&None));
}

#[test]
fn tracer_test_trace_sampling_zero_skips_context_and_emission() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    _reset_sampling_for_tests();
    set_sampling_policy(
        Signal::Traces,
        SamplingPolicy {
            default_rate: 0.0,
            overrides: BTreeMap::new(),
        },
    )
    .expect("sampling policy should set");

    let before = get_health_snapshot();
    let result = trace("unit.trace", || {
        let active = get_trace_context();
        assert_eq!(active.get("trace_id"), Some(&None));
        assert_eq!(active.get("span_id"), Some(&None));
        11_i32
    });

    assert_eq!(result, 11);
    let after = get_health_snapshot();
    assert_eq!(after.emitted_traces, before.emitted_traces);
    assert!(
        after.dropped_traces > before.dropped_traces,
        "sampling rejection must increment dropped traces at least once"
    );
}

#[test]
fn tracer_test_trace_queue_full_skips_context_and_emission() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    _reset_backpressure_for_tests();
    _reset_sampling_for_tests();
    reset_trace_context();
    set_queue_policy(QueuePolicy {
        logs_maxsize: 0,
        traces_maxsize: 1,
        metrics_maxsize: 0,
    });

    let held = try_acquire(Signal::Traces).expect("first acquire should succeed");
    let before = get_health_snapshot();
    let result = trace("unit.trace", || {
        let active = get_trace_context();
        assert_eq!(active.get("trace_id"), Some(&None));
        assert_eq!(active.get("span_id"), Some(&None));
        13_i32
    });
    release(held);

    assert_eq!(result, 13);
    let after = get_health_snapshot();
    assert_eq!(after.emitted_traces, before.emitted_traces);
    assert!(
        after.dropped_traces > before.dropped_traces,
        "queue rejection must increment dropped traces at least once"
    );
}

#[test]
fn tracer_test_active_trace_drop_without_ticket_is_a_noop() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    let active = ActiveTrace {
        ticket: None,
        noop_span: None,
        #[cfg(feature = "otel")]
        otel_span: None,
    };

    drop(active);
}
