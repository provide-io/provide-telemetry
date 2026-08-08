// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! The cross-language JCS number vectors — `spec/jcs_number_fixtures.yaml`.
//!
//! One vector per branch of the ECMAScript `Number::toString` algorithm that
//! RFC 8785 defers to. They exist because `spec/receipt_fixtures.yaml`'s seven
//! whole receipts are realistic payloads, and realistic payloads never reach the
//! exponent thresholds, the significand-trimming path, or the zero-padding
//! branch — so two real bugs shipped past them. Python rendered `1e21` as
//! `"0.1"`, colliding with `0.1` and `1e22` on a single receipt digest, and C#
//! rendered `1e-6` as `"1e-6"` where every other SDK emits `"0.000001"`. Both
//! are fixed; these vectors are what turn a regression into a failing test
//! rather than a shipped digest collision.
//!
//! Every case is checked twice: the number rendered alone through
//! [`canonical_number`], and the same number inside `{"v": ...}` through
//! [`canonical_json`]. A serializer can format correctly in isolation and still
//! lose the value in context.

use std::path::{Path, PathBuf};

use provide_telemetry::{canonical_json, canonical_number};
use serde::Deserialize;
use serde_json::{json, Value};

/// The committed vector count. Asserted before iterating so a parse that yields
/// nothing fails loudly instead of passing vacuously over an empty list.
const EXPECTED_CASES: usize = 21;

#[derive(Debug, Deserialize)]
struct NumberCase {
    id: String,
    branch: String,
    /// The number rendered on its own, e.g. `1e+21`.
    canonical: String,
    /// The same number inside `{"v": ...}`, e.g. `{"v":1e+21}`.
    in_object: String,
}

#[derive(Debug, Deserialize)]
struct Fixture {
    cases: Vec<NumberCase>,
}

/// Locate the fixture by walking up from the crate root rather than counting
/// parents, so the contract is still found when a runner copies or relocates
/// the crate tree.
fn fixture_path() -> PathBuf {
    let mut directory: Option<&Path> = Some(Path::new(env!("CARGO_MANIFEST_DIR")));
    while let Some(current) = directory {
        let candidate = current.join("spec").join("jcs_number_fixtures.yaml");
        if candidate.is_file() {
            return candidate;
        }
        directory = current.parent();
    }
    panic!("spec/jcs_number_fixtures.yaml not found in any parent of the crate root");
}

fn cases() -> Vec<NumberCase> {
    let path = fixture_path();
    let text = std::fs::read_to_string(&path).expect("the number fixture should be readable");
    let fixture: Fixture = serde_yaml::from_str(&text).expect("the number fixture should parse");
    assert!(
        fixture.cases.len() >= EXPECTED_CASES,
        "{} declared {} cases, want at least {EXPECTED_CASES}",
        path.display(),
        fixture.cases.len()
    );
    fixture.cases
}

/// Recover the binary64 a JavaScript producer would have canonicalized.
///
/// The value is read out of `in_object` through [`Value::as_f64`] rather than
/// being used as parsed. JavaScript has a single number type, so the fixture
/// spells `1e20` and `1e21` without a decimal point exactly as `JSON.stringify`
/// renders them, and `serde_json` types `9007199254740991` as an unsigned
/// integer. `as_f64` collapses both spellings onto the one float64 the vectors
/// are about, and the object form below is rebuilt from that f64 for the same
/// reason.
fn value_of(case: &NumberCase) -> f64 {
    let parsed: Value = serde_json::from_str(&case.in_object)
        .unwrap_or_else(|error| panic!("{}: parsing {}: {error}", case.id, case.in_object));
    parsed
        .get("v")
        .and_then(Value::as_f64)
        .unwrap_or_else(|| panic!("{}: {} has no float64 member `v`", case.id, case.in_object))
}

#[test]
fn every_number_renders_to_its_canonical_form() {
    for case in cases() {
        assert_eq!(
            canonical_number(value_of(&case)),
            case.canonical,
            "{} ({})",
            case.id,
            case.branch
        );
    }
}

#[test]
fn every_number_renders_the_same_inside_an_object() {
    for case in cases() {
        assert_eq!(
            canonical_json(&json!({ "v": value_of(&case) })),
            case.in_object,
            "{} ({})",
            case.id,
            case.branch
        );
    }
}
