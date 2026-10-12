// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! The canonical governance receipt vectors — `spec/receipt_fixtures.yaml`.
//!
//! Nothing here is derived from this crate. The canonical strings came from
//! `rfc8785` and the signatures from Python's `hmac`, so reproducing them byte
//! for byte is evidence of agreeing with the other four SDKs rather than with
//! ourselves. A canonicalizer that were merely self-consistent would pass its
//! own round-trip tests and still hash a value differently from every peer.

use provide_telemetry::{canonical_json, receipt_payload, sign_receipt, SignReceiptOptions};
use serde::Deserialize;
use serde_json::Value;

#[derive(Debug, Deserialize)]
struct ReceiptCase {
    id: String,
    key: String,
    input: Value,
    normalized: Value,
    canonical_json: String,
    receipt_id: String,
    timestamp: String,
    field_path: String,
    action: String,
    original_hash: String,
    payload: String,
    signature: String,
}

#[derive(Debug, Deserialize)]
struct Fixture {
    cases: Vec<ReceiptCase>,
}

fn cases() -> Vec<ReceiptCase> {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../spec/receipt_fixtures.yaml");
    let text =
        std::fs::read_to_string(path).expect("spec/receipt_fixtures.yaml should be readable");
    // A non-finite float has no `serde_json::Value` form. Rather than fail the
    // parse, serde-saphyr can hand it over as its YAML spelling (`.nan`, `.inf`,
    // `-.inf`); `non_finite_to_null` then does what serde_json does with a
    // non-finite f64. No fixture carries those spellings as quoted strings.
    let options = serde_saphyr::options! { reject_non_finite_typeless_float: false };
    let mut fixture: Fixture = serde_saphyr::from_str_with_options(&text, options)
        .expect("spec/receipt_fixtures.yaml should parse");
    assert!(!fixture.cases.is_empty(), "the contract must carry vectors");
    for case in &mut fixture.cases {
        non_finite_to_null(&mut case.input);
    }
    fixture.cases
}

/// Replace serde-saphyr's spellings of NaN and ±Infinity with `null`, as
/// `serde_json` stores a non-finite f64.
fn non_finite_to_null(value: &mut Value) {
    match value {
        Value::String(text) if matches!(text.as_str(), ".nan" | ".inf" | "-.inf") => {
            *value = Value::Null;
        }
        Value::Array(items) => items.iter_mut().for_each(non_finite_to_null),
        Value::Object(map) => map.values_mut().for_each(non_finite_to_null),
        _ => {}
    }
}

#[test]
fn receipt_vectors_match_exactly() {
    for case in cases() {
        assert_eq!(
            canonical_json(&case.normalized),
            case.canonical_json,
            "canonical JSON for {}",
            case.id
        );

        let receipt = sign_receipt(
            &case.normalized,
            SignReceiptOptions {
                receipt_id: &case.receipt_id,
                timestamp: &case.timestamp,
                field_path: &case.field_path,
                action: &case.action,
                service_name: "unused-by-the-signature",
                key: Some(case.key.as_bytes()),
            },
        );

        assert_eq!(
            receipt.original_hash, case.original_hash,
            "hash for {}",
            case.id
        );
        assert_eq!(
            receipt_payload(&receipt),
            case.payload,
            "payload for {}",
            case.id
        );
        assert_eq!(
            receipt.hmac.as_deref(),
            Some(case.signature.as_str()),
            "signature for {}",
            case.id
        );
    }
}

/// `input` and `normalized` differ only where JCS cannot encode the input —
/// NaN and ±Infinity, which the contract fixes as `null`. Rust reaches that
/// normalization without a code path for it: `serde_json::Number` cannot hold a
/// non-finite float, so `input`, once in a `serde_json::Value`, already *is*
/// `normalized`.
#[test]
fn non_finite_inputs_normalize_before_reaching_the_canonicalizer() {
    for case in cases() {
        assert_eq!(
            case.input, case.normalized,
            "{} should deserialize to its normalized form",
            case.id
        );
    }
}
