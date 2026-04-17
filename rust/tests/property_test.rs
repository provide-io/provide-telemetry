// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;

use proptest::prelude::*;
use serde_json::{json, Value};

use provide_telemetry::testing::{acquire_test_state_lock, reset_telemetry_state};
use provide_telemetry::{
    compute_error_fingerprint, event, extract_w3c_context, get_sampling_policy, parse_baggage,
    sanitize_payload, set_sampling_policy, set_strict_schema, should_sample, SamplingPolicy, Signal,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn any_signal() -> impl Strategy<Value = Signal> {
    prop_oneof![Just(Signal::Logs), Just(Signal::Traces), Just(Signal::Metrics),]
}

/// Generate a valid W3C traceparent header.
fn valid_traceparent() -> impl Strategy<Value = String> {
    (
        // version: 2 hex chars, not "ff"
        "[0-9a-f]{2}".prop_filter("version must not be ff", |v| v != "ff"),
        // trace_id: 32 hex chars, not all zeros
        "[0-9a-f]{32}".prop_filter("trace_id must not be all zeros", |t| {
            t != "00000000000000000000000000000000"
        }),
        // span_id: 16 hex chars, not all zeros
        "[0-9a-f]{16}"
            .prop_filter("span_id must not be all zeros", |s| s != "0000000000000000"),
        // flags: 2 hex chars
        "[0-9a-f]{2}",
    )
        .prop_map(|(v, t, s, f)| format!("{v}-{t}-{s}-{f}"))
}

// ---------------------------------------------------------------------------
// Sampling
// ---------------------------------------------------------------------------

proptest! {
    #![proptest_config(ProptestConfig::with_cases(50))]

    #[test]
    fn sampling_rate_zero_never_samples(signal in any_signal()) {
        let _guard = acquire_test_state_lock();
        reset_telemetry_state();
        set_sampling_policy(signal, SamplingPolicy {
            default_rate: 0.0,
            overrides: BTreeMap::new(),
        }).unwrap();
        for _ in 0..100 {
            prop_assert!(!should_sample(signal, Some("anything")).unwrap());
            prop_assert!(!should_sample(signal, None).unwrap());
        }
    }

    #[test]
    fn sampling_rate_one_always_samples(signal in any_signal()) {
        let _guard = acquire_test_state_lock();
        reset_telemetry_state();
        set_sampling_policy(signal, SamplingPolicy {
            default_rate: 1.0,
            overrides: BTreeMap::new(),
        }).unwrap();
        for _ in 0..100 {
            prop_assert!(should_sample(signal, Some("anything")).unwrap());
            prop_assert!(should_sample(signal, None).unwrap());
        }
    }

    #[test]
    fn sampling_roundtrip_preserves_clamped_rate(
        signal in any_signal(),
        rate in -1.0f64..=2.0,
    ) {
        let _guard = acquire_test_state_lock();
        reset_telemetry_state();
        let returned = set_sampling_policy(signal, SamplingPolicy {
            default_rate: rate,
            overrides: BTreeMap::new(),
        }).unwrap();
        let fetched = get_sampling_policy(signal).unwrap();
        prop_assert_eq!(returned, fetched.clone());
        prop_assert!(fetched.default_rate >= 0.0);
        prop_assert!(fetched.default_rate <= 1.0);
    }
}

// ---------------------------------------------------------------------------
// PII / Sanitize
// ---------------------------------------------------------------------------

proptest! {
    #![proptest_config(ProptestConfig::with_cases(50))]

    #[test]
    fn sanitize_always_redacts_default_sensitive_keys(
        value in "[a-zA-Z0-9]{1,40}",
    ) {
        let _guard = acquire_test_state_lock();
        reset_telemetry_state();
        let payload = json!({
            "password": value,
            "token": value,
            "api_key": value,
            "safe_field": "visible",
        });
        let result = sanitize_payload(&payload, true, 10);
        let obj = result.as_object().unwrap();
        prop_assert_eq!(obj.get("password").unwrap(), &Value::String("***".into()));
        prop_assert_eq!(obj.get("token").unwrap(), &Value::String("***".into()));
        prop_assert_eq!(obj.get("api_key").unwrap(), &Value::String("***".into()));
        prop_assert_eq!(
            obj.get("safe_field").unwrap(),
            &Value::String("visible".into())
        );
    }

    #[test]
    fn sanitize_disabled_returns_original(
        key in "[a-z]{1,20}",
        value in "[a-zA-Z0-9]{1,40}",
    ) {
        let payload = json!({ key: value });
        let result = sanitize_payload(&payload, false, 10);
        prop_assert_eq!(result, payload);
    }

    #[test]
    fn sanitize_detects_aws_like_keys(
        suffix in "[A-Z0-9]{16}",
    ) {
        let _guard = acquire_test_state_lock();
        reset_telemetry_state();
        let fake_key = format!("AKIA{suffix}");
        let payload = json!({ "data": fake_key });
        let result = sanitize_payload(&payload, true, 10);
        let obj = result.as_object().unwrap();
        prop_assert_eq!(
            obj.get("data").unwrap(),
            &Value::String("***".into()),
            "AWS-like key '{}' should be redacted",
            fake_key
        );
    }
}

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

proptest! {
    #![proptest_config(ProptestConfig::with_cases(100))]

    #[test]
    fn event_three_valid_segments_succeeds(
        a in "[a-z][a-z0-9_]{0,10}",
        b in "[a-z][a-z0-9_]{0,10}",
        c in "[a-z][a-z0-9_]{0,10}",
    ) {
        set_strict_schema(false);
        let result = event(&[&a, &b, &c]);
        prop_assert!(result.is_ok(), "3-segment event should succeed: {:?}", result);
        let ev = result.unwrap();
        prop_assert_eq!(ev.domain, a);
        prop_assert_eq!(ev.action, b);
        prop_assert_eq!(ev.status, c);
        prop_assert!(ev.resource.is_none());
    }

    #[test]
    fn event_four_valid_segments_succeeds(
        a in "[a-z][a-z0-9_]{0,10}",
        b in "[a-z][a-z0-9_]{0,10}",
        c in "[a-z][a-z0-9_]{0,10}",
        d in "[a-z][a-z0-9_]{0,10}",
    ) {
        set_strict_schema(false);
        let result = event(&[&a, &b, &c, &d]);
        prop_assert!(result.is_ok(), "4-segment event should succeed: {:?}", result);
        let ev = result.unwrap();
        prop_assert_eq!(ev.domain, a);
        prop_assert_eq!(ev.action, b);
        prop_assert_eq!(ev.resource, Some(c));
        prop_assert_eq!(ev.status, d);
    }

    #[test]
    fn event_wrong_segment_count_fails(count in (0usize..=10).prop_filter(
        "exclude 3 and 4",
        |c| *c < 3 || *c > 4,
    )) {
        set_strict_schema(false);
        let segments: Vec<&str> = (0..count).map(|_| "seg").collect();
        let result = event(&segments);
        prop_assert!(result.is_err(), "segment count {} should fail", count);
    }

    #[test]
    fn event_strict_rejects_hyphens(
        a in "[a-z][a-z0-9_]{0,10}",
    ) {
        set_strict_schema(true);
        let result = event(&[&a, "has-hyphen", "ok"]);
        prop_assert!(result.is_err(), "strict should reject hyphens");
        set_strict_schema(false);
    }
}

// ---------------------------------------------------------------------------
// Propagation
// ---------------------------------------------------------------------------

proptest! {
    #![proptest_config(ProptestConfig::with_cases(200))]

    #[test]
    fn parse_baggage_never_panics(input in "\\PC{0,500}") {
        let _ = parse_baggage(&input);
    }

    #[test]
    fn parse_baggage_no_empty_keys(input in "\\PC{0,500}") {
        let result = parse_baggage(&input);
        for key in result.keys() {
            prop_assert!(!key.is_empty(), "empty key in parse_baggage result");
        }
    }

    #[test]
    fn parse_baggage_roundtrip_simple_pairs(
        pairs in prop::collection::vec(
            ("[a-z]{1,10}", "[a-z0-9]{1,20}"),
            1..=5,
        ),
    ) {
        let header = pairs
            .iter()
            .map(|(k, v)| format!("{k}={v}"))
            .collect::<Vec<_>>()
            .join(",");
        let result = parse_baggage(&header);
        // Deduplicated by last-wins, so just check all returned keys exist
        for key in result.keys() {
            prop_assert!(
                pairs.iter().any(|(k, _)| k == key),
                "unexpected key: {}",
                key
            );
        }
        for (k, v) in &result {
            let expected = pairs.iter().rev().find(|(pk, _)| pk == k).unwrap();
            prop_assert_eq!(v, &expected.1);
        }
    }

    #[test]
    fn extract_w3c_context_valid_traceparent_always_parses(tp in valid_traceparent()) {
        let ctx = extract_w3c_context(Some(&tp), None, None);
        prop_assert!(ctx.trace_id.is_some(), "trace_id should be set for valid traceparent");
        prop_assert!(ctx.span_id.is_some(), "span_id should be set for valid traceparent");
        prop_assert!(ctx.traceparent.is_some(), "traceparent should be preserved");
    }

    #[test]
    fn extract_w3c_context_arbitrary_never_panics(
        tp in proptest::option::of("\\PC{0,200}"),
        ts in proptest::option::of("\\PC{0,200}"),
        bg in proptest::option::of("\\PC{0,200}"),
    ) {
        let _ = extract_w3c_context(
            tp.as_deref(),
            ts.as_deref(),
            bg.as_deref(),
        );
    }
}

// ---------------------------------------------------------------------------
// Fingerprint
// ---------------------------------------------------------------------------

proptest! {
    #![proptest_config(ProptestConfig::with_cases(200))]

    #[test]
    fn fingerprint_always_12_hex(
        error_name in "[a-zA-Z]{1,30}",
        stack in proptest::option::of("[a-zA-Z0-9 /\n]{0,200}"),
    ) {
        let fp = compute_error_fingerprint(&error_name, stack.as_deref());
        prop_assert_eq!(fp.len(), 12, "fingerprint length should be 12, got {}", fp.len());
        prop_assert!(
            fp.chars().all(|c| c.is_ascii_hexdigit()),
            "non-hex char in fingerprint: {}",
            fp
        );
    }

    #[test]
    fn fingerprint_deterministic(
        error_name in "[a-zA-Z]{1,30}",
        stack in proptest::option::of("[a-zA-Z0-9 /\n]{0,200}"),
    ) {
        let fp1 = compute_error_fingerprint(&error_name, stack.as_deref());
        let fp2 = compute_error_fingerprint(&error_name, stack.as_deref());
        prop_assert_eq!(fp1, fp2, "same input must produce same fingerprint");
    }

    #[test]
    fn fingerprint_different_inputs_different_outputs(
        a in "[a-zA-Z]{1,20}",
        b in "[a-zA-Z]{1,20}",
    ) {
        prop_assume!(a != b);
        let fp_a = compute_error_fingerprint(&a, None);
        let fp_b = compute_error_fingerprint(&b, None);
        // Not a hard guarantee (hash collisions), but extremely unlikely for
        // distinct short strings so we assert it for coverage.
        prop_assert_ne!(fp_a, fp_b, "distinct names should (almost always) differ");
    }
}
