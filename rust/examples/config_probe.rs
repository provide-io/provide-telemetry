// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Emit observed config metadata for the Rust SDK.
//!
//! The probe never reads `spec/telemetry-api.yaml`. Applicability is determined
//! differentially: build the config with a clean environment for the baseline,
//! then rebuild once per variable with that variable set. A variable this SDK
//! parses changes the config; one it ignores leaves it identical. The reported
//! default and type come from the baseline config object, serialized through
//! serde rather than declared by hand.

use std::collections::BTreeMap;
use std::env;

use provide_telemetry::TelemetryConfig;
use serde_json::{Map, Value};

/// Values chosen to differ from every spec default, including valid values for
/// validated fields (a rejected value proves the variable is read but leaves no
/// config object to diff).
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

const OWNED_PREFIXES: &[&str] = &["PROVIDE_", "OTEL_"];

fn clean_env() -> Vec<(String, String)> {
    env::vars()
        .filter(|(k, _)| !OWNED_PREFIXES.iter().any(|p| k.starts_with(p)))
        .collect()
}

/// Flatten serialized config into dotted-path -> (rendered value, type name).
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
            out.insert(
                prefix.trim_end_matches('.').to_string(),
                (joined, "str".into()),
            );
        }
        Value::Bool(b) => {
            out.insert(
                prefix.trim_end_matches('.').to_string(),
                (b.to_string(), "bool".into()),
            );
        }
        Value::Number(n) => {
            let ty = if n.is_f64() && n.as_f64().is_some_and(|f| f.fract() != 0.0) {
                "float"
            } else if n.is_i64() || n.is_u64() {
                "int"
            } else {
                "float"
            };
            out.insert(
                prefix.trim_end_matches('.').to_string(),
                (render_scalar(value), ty.into()),
            );
        }
        Value::Null => {
            out.insert(
                prefix.trim_end_matches('.').to_string(),
                (String::new(), "str".into()),
            );
        }
        Value::String(s) => {
            out.insert(
                prefix.trim_end_matches('.').to_string(),
                (s.clone(), "str".into()),
            );
        }
    }
}

fn render_scalar(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        Value::Bool(b) => b.to_string(),
        Value::Null => String::new(),
        other => other.to_string(),
    }
}

fn build(env_pairs: &[(String, String)]) -> Result<BTreeMap<String, (String, String)>, String> {
    // SAFETY: the probe is single-threaded; nothing else touches the environment.
    unsafe {
        for (key, _) in env::vars() {
            env::remove_var(&key);
        }
        for (key, value) in env_pairs {
            env::set_var(key, value);
        }
    }
    let config = TelemetryConfig::from_env().map_err(|e| e.to_string())?;
    let serialized = serde_json::to_value(&config).map_err(|e| e.to_string())?;
    let mut flat = BTreeMap::new();
    flatten(&serialized, "", &mut flat);
    Ok(flat)
}

/// Express a numeric default in the units the environment variable uses. An SDK
/// may store a `..._TIMEOUT_SECONDS` value in milliseconds; rather than
/// hardcoding which fields are scaled, measure the SDK's own conversion factor
/// from a known probe value.
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

fn main() {
    let env_vars: Vec<String> = env::args().skip(1).collect();
    if env_vars.is_empty() {
        eprintln!("usage: config_probe ENV_VAR [ENV_VAR ...]");
        std::process::exit(2);
    }

    let base_env = clean_env();
    let baseline = match build(&base_env) {
        Ok(flat) => flat,
        Err(err) => {
            eprintln!("baseline config failed: {err}");
            std::process::exit(1);
        }
    };

    let mut entries = Map::new();
    for env_var in &env_vars {
        let mut settled = false;
        let mut rejected = false;

        for probe_value in PROBE_VALUES {
            let mut env_pairs = base_env.clone();
            env_pairs.push((env_var.clone(), (*probe_value).to_string()));

            let observed = match build(&env_pairs) {
                Ok(flat) => flat,
                // A rejected value still proves the variable is read.
                Err(_) => {
                    rejected = true;
                    continue;
                }
            };

            let changed: Option<&String> = baseline
                .iter()
                .find(|(key, (value, _))| {
                    observed.get(*key).is_some_and(|(other, _)| other != value)
                })
                .map(|(key, _)| key);

            if let Some(key) = changed {
                let (base_value, base_type) = &baseline[key];
                let (observed_value, _) = &observed[key];
                let mut entry = Map::new();
                entry.insert("type".into(), Value::String(base_type.clone()));
                entry.insert(
                    "default".into(),
                    Value::String(default_in_variable_units(
                        base_value,
                        probe_value,
                        observed_value,
                    )),
                );
                entry.insert("applicable".into(), Value::Bool(true));
                entries.insert(env_var.clone(), Value::Object(entry));
                settled = true;
                break;
            }

            // A key the probe *added* counts too: an empty HashMap serializes to
            // `{}` and contributes no flattened keys, so comparing only shared
            // keys would read as "the SDK ignores this variable".
            if observed.keys().any(|key| !baseline.contains_key(key)) {
                let mut entry = Map::new();
                entry.insert("type".into(), Value::String("str".into()));
                entry.insert("default".into(), Value::String(String::new()));
                entry.insert("applicable".into(), Value::Bool(true));
                entries.insert(env_var.clone(), Value::Object(entry));
                settled = true;
                break;
            }
        }

        if !settled {
            let mut entry = Map::new();
            entry.insert("type".into(), Value::String(String::new()));
            entry.insert("default".into(), Value::String(String::new()));
            entry.insert("applicable".into(), Value::Bool(rejected));
            entries.insert(env_var.clone(), Value::Object(entry));
        }
    }

    let payload = serde_json::json!({ "language": "rust", "entries": Value::Object(entries) });
    println!("{payload}");
}
