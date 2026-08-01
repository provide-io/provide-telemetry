// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

//! Fuzz the propagation surface — the only input that arrives from the network.
//!
//! Every other input to this crate comes from the operator (env vars, config
//! structs) or the developer (log calls). W3C headers arrive from whoever made
//! the HTTP request, so these parsers are the attack surface, and the invariants
//! below are the ones an attacker must not be able to break:
//!
//! * nothing panics, whatever the bytes;
//! * a parsed trace/span id is always well-formed hex of the right length, so a
//!   malformed inbound header can never poison an outbound one;
//! * baggage keys are always RFC 7230 tokens and values never carry control
//!   characters, so a key can never forge a log record.
//!
//! Driven by proptest rather than cargo-fuzz: cargo-fuzz needs a nightly
//! toolchain, and this crate builds on stable. Mirrors tests/fuzz in Python,
//! go/fuzz_test.go and typescript/tests/fuzz/.

use proptest::prelude::*;
use provide_telemetry::{extract_w3c_context, parse_baggage};

const HEX: &str = "0123456789abcdef";
const ZERO_TRACE: &str = "00000000000000000000000000000000";
const ZERO_SPAN: &str = "0000000000000000";
const TOKEN_CHARS: &str = "!#$%&'*+-.^_`|~";

fn is_token(key: &str) -> bool {
    !key.is_empty()
        && key
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || TOKEN_CHARS.contains(c))
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(400))]

    #[test]
    fn parse_baggage_never_panics(raw in ".{0,2048}") {
        let _ = parse_baggage(&raw);
    }

    /// A key that is not a token could forge a log record downstream.
    #[test]
    fn parse_baggage_keys_are_always_tokens(raw in ".{0,2048}") {
        for key in parse_baggage(&raw).keys() {
            prop_assert!(is_token(key), "non-token key survived: {key:?}");
        }
    }

    #[test]
    fn parse_baggage_values_never_carry_controls(raw in ".{0,2048}") {
        for value in parse_baggage(&raw).values() {
            prop_assert!(
                value.chars().all(|c| c == '\t' || !c.is_control()),
                "control character survived in value: {value:?}"
            );
        }
    }

    #[test]
    fn extract_w3c_context_never_panics(
        tp in ".{0,1024}",
        ts in ".{0,1024}",
        bg in ".{0,1024}",
    ) {
        let _ = extract_w3c_context(Some(&tp), Some(&ts), Some(&bg));
    }

    /// A malformed inbound header must never yield an id we would propagate.
    #[test]
    fn parsed_ids_are_always_well_formed(tp in ".{0,1024}") {
        let ctx = extract_w3c_context(Some(&tp), None, None);

        if let Some(trace_id) = ctx.trace_id.as_deref() {
            prop_assert_eq!(trace_id.len(), 32);
            prop_assert!(trace_id.chars().all(|c| HEX.contains(c)));
            prop_assert_ne!(trace_id, ZERO_TRACE);
        }
        if let Some(span_id) = ctx.span_id.as_deref() {
            prop_assert_eq!(span_id.len(), 16);
            prop_assert!(span_id.chars().all(|c| HEX.contains(c)));
            prop_assert_ne!(span_id, ZERO_SPAN);
        }
        // The pair is all-or-nothing; a half-parsed header must not be forwarded.
        prop_assert_eq!(ctx.trace_id.is_none(), ctx.span_id.is_none());
        if ctx.trace_id.is_none() {
            prop_assert!(ctx.traceparent.is_none());
        }
    }

    #[test]
    fn well_formed_traceparents_round_trip(
        trace_id in "[0-9a-f]{32}",
        span_id in "[0-9a-f]{16}",
    ) {
        prop_assume!(trace_id != ZERO_TRACE && span_id != ZERO_SPAN);
        let header = format!("00-{trace_id}-{span_id}-01");

        let ctx = extract_w3c_context(Some(&header), None, None);

        prop_assert_eq!(ctx.trace_id.as_deref(), Some(trace_id.as_str()));
        prop_assert_eq!(ctx.span_id.as_deref(), Some(span_id.as_str()));
        prop_assert_eq!(ctx.traceparent.as_deref(), Some(header.as_str()));
    }
}
