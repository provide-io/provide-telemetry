// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Observe this SDK's real config defaults, one environment variable at a time.
//!
//! Nothing here reads `spec/telemetry-api.yaml`. Applicability is determined
//! differentially: build a config from an empty environment for the baseline,
//! then rebuild once per variable with only that variable set. A variable this
//! SDK parses changes the config object; one it ignores leaves it identical.
//! The reported default and type come from the baseline config serialized
//! through serde, so a probe can never claim support the parser does not have.
//!
//! `TelemetryConfig::from_map` is what makes this safe to run in-process: the
//! comparison never touches the real environment, so the executable contract
//! test can run alongside every other test rather than only in a subprocess.

use std::collections::BTreeMap;
use std::collections::HashMap;

use serde::Serialize;
use serde_json::Value;

use super::TelemetryConfig;

/// Values chosen to differ from every spec default, including valid values for
/// validated fields — a rejected value proves the variable is read, but leaves
/// no config object to diff.
const PROBE_VALUES: &[&str] = &[
    "DEBUG",
    "json",
    "red",
    "3",
    "1327",
    "0.4271",
    "probe-sentinel-value",
    "false",
    "true",
    "http://probe.invalid:4318",
    "probe-module=DEBUG",
    "probe-key=probe-value",
];

/// One environment variable as observed from a real [`TelemetryConfig`].
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct ProbedConfigEntry {
    #[serde(rename = "type")]
    pub type_name: String,
    pub default: String,
    pub applicable: bool,
}

impl ProbedConfigEntry {
    fn unsupported() -> Self {
        Self {
            type_name: String::new(),
            default: String::new(),
            applicable: false,
        }
    }
}

/// Flatten a serialized config into dotted-path -> (rendered value, type name).
/// Arrays and objects render as strings so comparison is by value.
fn flatten(value: &Value, prefix: &str, out: &mut BTreeMap<String, (String, String)>) {
    match value {
        Value::Object(map) => {
            for (key, nested) in map {
                flatten(nested, &format!("{prefix}{key}."), out);
            }
        }
        Value::Array(items) => {
            let joined = items
                .iter()
                .map(render_scalar)
                .collect::<Vec<_>>()
                .join(",");
            insert_flat(out, prefix, joined, "str");
        }
        Value::Bool(flag) => insert_flat(out, prefix, flag.to_string(), "bool"),
        Value::Number(number) => {
            let type_name = if number.is_i64() || number.is_u64() {
                "int"
            } else {
                "float"
            };
            insert_flat(out, prefix, render_scalar(value), type_name);
        }
        Value::Null => insert_flat(out, prefix, String::new(), "str"),
        Value::String(text) => insert_flat(out, prefix, text.clone(), "str"),
    }
}

fn insert_flat(
    out: &mut BTreeMap<String, (String, String)>,
    prefix: &str,
    value: String,
    type_name: &str,
) {
    out.insert(
        prefix.trim_end_matches('.').to_string(),
        (value, type_name.to_string()),
    );
}

/// Render a value the way a shell would have supplied it: a string is its own
/// text, everything else is its JSON form.
fn render_scalar(value: &Value) -> String {
    match value {
        Value::String(text) => text.clone(),
        other => other.to_string(),
    }
}

fn build(env: &HashMap<String, String>) -> Option<BTreeMap<String, (String, String)>> {
    let config = TelemetryConfig::from_map(env).ok()?;
    let serialized = serde_json::to_value(&config).ok()?;
    let mut flat = BTreeMap::new();
    flatten(&serialized, "", &mut flat);
    Some(flat)
}

/// Express a numeric default in the units the environment variable uses.
///
/// An SDK may store a `..._TIMEOUT_SECONDS` value in milliseconds. Rather than
/// hardcoding which fields are scaled, measure this SDK's own conversion factor
/// from a known probe value and divide the baseline by it.
fn default_in_variable_units(baseline: &str, probe_value: &str, observed: &str) -> String {
    let (Ok(base), Ok(probed), Ok(obs)) = (
        baseline.parse::<f64>(),
        probe_value.parse::<f64>(),
        observed.parse::<f64>(),
    ) else {
        return baseline.to_string();
    };
    if probed == 0.0 || obs == 0.0 {
        return baseline.to_string();
    }
    let scale = obs / probed;
    if scale == 1.0 || scale <= 0.0 || scale.fract() != 0.0 {
        return baseline.to_string();
    }
    let scaled = base / scale;
    if scaled.fract() == 0.0 {
        format!("{}", scaled as i64)
    } else {
        format!("{scaled}")
    }
}

/// Probe one variable against the baseline, returning `None` when this SDK
/// neither reacts to it nor rejects a value for it.
///
/// `probe_values` is a parameter so a test can narrow it to values this SDK
/// only ever rejects, which is the one arm the full set cannot reach: for every
/// variable in the contract, some probe value parses *and* changes the config
/// before the loop runs out.
fn probe_one(
    baseline: &BTreeMap<String, (String, String)>,
    env_var: &str,
    probe_values: &[&str],
) -> Option<ProbedConfigEntry> {
    let mut rejected = false;
    for probe_value in probe_values {
        let env: HashMap<String, String> =
            HashMap::from([(env_var.to_string(), (*probe_value).to_string())]);
        let Some(observed) = build(&env) else {
            // A rejected value still proves the variable is read.
            rejected = true;
            continue;
        };

        if let Some(key) = baseline
            .iter()
            .find(|(key, (value, _))| observed.get(*key).is_some_and(|(other, _)| other != value))
            .map(|(key, _)| key)
        {
            let (base_value, base_type) = &baseline[key];
            let (observed_value, _) = &observed[key];
            return Some(ProbedConfigEntry {
                type_name: base_type.clone(),
                default: default_in_variable_units(base_value, probe_value, observed_value),
                applicable: true,
            });
        }

        // A key the probe *added* counts too: an empty map serializes to `{}`
        // and contributes no flattened keys, so comparing only shared keys
        // would read as "the SDK ignores this variable".
        if observed.keys().any(|key| !baseline.contains_key(key)) {
            return Some(ProbedConfigEntry {
                type_name: "str".to_string(),
                default: String::new(),
                applicable: true,
            });
        }
    }
    rejected.then(|| ProbedConfigEntry {
        applicable: true,
        ..ProbedConfigEntry::unsupported()
    })
}

/// Report what this SDK actually does with each named environment variable.
///
/// Used by both `rust/tests/config_applicability.rs` and the
/// `config_probe` example that `spec/check_config_parity.py` shells out to, so
/// the in-repo gate and the cross-language gate cannot disagree about what was
/// measured.
pub fn config_defaults_probe(env_vars: &[String]) -> BTreeMap<String, ProbedConfigEntry> {
    let baseline = build(&HashMap::new()).expect("an empty environment must yield a valid config");
    env_vars
        .iter()
        .map(|env_var| {
            let entry = probe_one(&baseline, env_var, PROBE_VALUES)
                .unwrap_or_else(ProbedConfigEntry::unsupported);
            (env_var.clone(), entry)
        })
        .collect()
}

#[cfg(test)]
#[path = "probe_tests.rs"]
mod tests;
