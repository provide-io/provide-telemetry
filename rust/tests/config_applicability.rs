// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! The config contract, executed rather than asserted by hand.
//!
//! `spec/telemetry-api.yaml` declares, per environment variable, its type, its
//! default, and which SDKs support it. This test measures the same three facts
//! from a real `TelemetryConfig` and diffs them. Nothing here restates a
//! default: a variable Rust silently stopped parsing, or one whose default
//! drifted, fails as an applicability or value mismatch.
//!
//! `spec/check_config_parity.py` runs the identical comparison across all five
//! SDKs by shelling out to `examples/config_probe.rs`. Both read the same
//! measurement function, so this test is the fast in-repo half of that gate
//! rather than a second, drift-prone copy of it.

use std::collections::BTreeMap;

use provide_telemetry::testing::{acquire_test_state_lock, config_defaults_probe};
use provide_telemetry::{setup_telemetry, shutdown_telemetry, TelemetryConfig};
use serde_json::Value;

const LANGUAGE: &str = "rust";

/// One contract entry, reduced to the facts a probe can observe.
#[derive(Debug)]
struct Expected {
    type_name: String,
    default: String,
    applicable: bool,
    /// False for variables this SDK honours outside `TelemetryConfig` — the
    /// pretty-renderer colours are read from the environment at render time, so
    /// a probe that inspects the config object genuinely cannot see them.
    probe_visible: bool,
}

fn spec_document() -> Value {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../spec/telemetry-api.yaml");
    let text = std::fs::read_to_string(path).expect("spec/telemetry-api.yaml should be readable");
    serde_yaml::from_str(&text).expect("spec/telemetry-api.yaml should parse")
}

/// Render a YAML scalar the way a probe reports it: an absent default is the
/// empty string, so no probe has to emit the literal text "None".
fn render_default(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::String(text) => text.clone(),
        other => other.to_string(),
    }
}

fn expected_entries() -> BTreeMap<String, Expected> {
    let spec = spec_document();
    let groups = spec["config_defaults"]
        .as_object()
        .expect("config_defaults should be a mapping");

    let mut expected = BTreeMap::new();
    for entries in groups.values() {
        for entry in entries.as_array().expect("each group should be a list") {
            let env = entry["env"]
                .as_str()
                .expect("every entry should name an env var");
            let overrides = &entry["overrides"][LANGUAGE];
            let applicable = entry["applicability"]
                .as_array()
                .is_some_and(|langs| langs.iter().any(|lang| lang == LANGUAGE));
            expected.insert(
                env.to_string(),
                Expected {
                    type_name: render_default(pick(overrides, "type", &entry["type"])),
                    default: render_default(pick(overrides, "default", &entry["default"])),
                    applicable,
                    probe_visible: overrides["probe_visible"].as_bool().unwrap_or(true),
                },
            );
        }
    }
    expected
}

/// A documented per-language deviation wins over the canonical value; anything
/// else keeps the canonical value canonical.
fn pick<'a>(overrides: &'a Value, key: &str, fallback: &'a Value) -> &'a Value {
    match &overrides[key] {
        Value::Null => fallback,
        override_value => override_value,
    }
}

/// Compare defaults by value, so `1` and `1.0` agree for a numeric variable.
/// Only numeric types get this: for a string variable those really are
/// different defaults and must still fail.
fn defaults_match(type_name: &str, expected: &str, observed: &str) -> bool {
    if expected == observed {
        return true;
    }
    if type_name != "int" && type_name != "float" {
        return false;
    }
    match (expected.parse::<f64>(), observed.parse::<f64>()) {
        (Ok(left), Ok(right)) => left == right,
        _ => false,
    }
}

#[test]
fn rust_config_probe_matches_applicable_contract_defaults() {
    let expected = expected_entries();
    let names: Vec<String> = expected.keys().cloned().collect();
    let observed = config_defaults_probe(&names);

    let mut errors: Vec<String> = Vec::new();
    for (env, want) in &expected {
        let got = &observed[env];
        // Skipped before applicability: the variable is supported, the probe
        // just cannot see it, so its `applicable: false` says nothing.
        if !want.probe_visible {
            continue;
        }
        if want.applicable != got.applicable {
            errors.push(format!(
                "{env}: spec says applicable={} for {LANGUAGE}, but the SDK reports {}",
                want.applicable, got.applicable
            ));
            continue;
        }
        if !want.applicable {
            continue;
        }
        if want.type_name != got.type_name {
            errors.push(format!(
                "{env}: type spec={:?} observed={:?}",
                want.type_name, got.type_name
            ));
        }
        if !defaults_match(&want.type_name, &want.default, &got.default) {
            errors.push(format!(
                "{env}: default spec={:?} observed={:?}",
                want.default, got.default
            ));
        }
    }

    assert!(
        errors.is_empty(),
        "config contract drift:\n  {}",
        errors.join("\n  ")
    );
    assert!(
        expected.values().any(|want| !want.applicable),
        "the contract must still mark something inapplicable to Rust, or this test proves nothing"
    );
}

/// An out-of-range rate in an explicit config is refused outright.
///
/// The temptation is to clamp: `apply_policies` would happily pin 1.01 to 1.0
/// and install it. But `get_runtime_config()` would then keep reporting 1.01,
/// so the snapshot and the policy in force would be two different things. Every
/// other SDK rejects here, and so does this one.
#[test]
fn invalid_shared_config_is_rejected_without_clamping() {
    let _guard = acquire_test_state_lock();
    shutdown_telemetry(None).expect("pre-test shutdown should succeed");

    let mut config = TelemetryConfig::default();
    config.sampling.logs_rate = 1.01;

    let err = setup_telemetry(Some(config)).expect_err("a rate above one must be rejected");

    assert!(
        err.message.contains("PROVIDE_SAMPLING_LOGS_RATE"),
        "the message should name the variable a caller would recognise: {}",
        err.message
    );
    assert!(
        provide_telemetry::get_runtime_config().is_none(),
        "a rejected config must not be installed, clamped or otherwise"
    );

    shutdown_telemetry(None).expect("shutdown should succeed");
}
