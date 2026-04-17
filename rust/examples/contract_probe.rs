// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

//! Contract probe interpreter for cross-language parity testing.
//!
//! Reads `PROVIDE_CONTRACT_CASE`, loads `../spec/contract_fixtures.yaml`,
//! finds the named case, executes each step against the real public API,
//! and emits `{"case":"<id>","variables":{...}}` to stdout.

use std::collections::BTreeMap;

use serde_json::{json, Value};

/// Holds RAII guards that must stay alive for the duration of the case.
struct Guards {
    _propagation: Option<provide_telemetry::propagation::PropagationGuard>,
    _context: Vec<provide_telemetry::context::ContextGuard>,
}

impl Guards {
    fn new() -> Self {
        Self {
            _propagation: None,
            _context: Vec::new(),
        }
    }
}

fn as_str<'a>(v: &'a Value, key: &str) -> &'a str {
    v.get(key).and_then(Value::as_str).unwrap_or("")
}

fn as_object(v: &Value, key: &str) -> BTreeMap<String, Value> {
    v.get(key)
        .and_then(Value::as_object)
        .map(|m| m.iter().map(|(k, v)| (k.clone(), v.clone())).collect())
        .unwrap_or_default()
}

fn exec_setup(step: &Value) {
    // Apply overrides as env vars before calling setup_telemetry.
    let overrides = as_object(step, "overrides");
    for (key, value) in &overrides {
        let env_key = match key.as_str() {
            "serviceName" => "PROVIDE_TELEMETRY_SERVICE_NAME",
            "environment" => "PROVIDE_TELEMETRY_ENVIRONMENT",
            "version" => "PROVIDE_TELEMETRY_VERSION",
            _ => continue,
        };
        if let Some(s) = value.as_str() {
            unsafe { std::env::set_var(env_key, s) };
        }
    }
    provide_telemetry::setup_telemetry().ok();
}

fn exec_setup_invalid(step: &Value, variables: &mut BTreeMap<String, Value>) {
    let into = as_str(step, "into");
    let overrides = as_object(step, "overrides");

    // Apply overrides as env vars to trigger validation errors.
    for (key, value) in &overrides {
        let env_key = match key.as_str() {
            "samplingLogsRate" => "PROVIDE_SAMPLING_LOGS_RATE",
            "samplingTracesRate" => "PROVIDE_SAMPLING_TRACES_RATE",
            "samplingMetricsRate" => "PROVIDE_SAMPLING_METRICS_RATE",
            "serviceName" => "PROVIDE_TELEMETRY_SERVICE_NAME",
            _ => continue,
        };
        let val_str = match value {
            Value::Number(n) => n.to_string(),
            Value::String(s) => s.clone(),
            _ => value.to_string(),
        };
        unsafe { std::env::set_var(env_key, &val_str) };
    }

    let result = provide_telemetry::setup_telemetry();
    let raised = result.is_err();
    let error = result.err().map(|e| e.to_string()).unwrap_or_default();

    // Clean up the env vars we set.
    for key in overrides.keys() {
        let env_key = match key.as_str() {
            "samplingLogsRate" => "PROVIDE_SAMPLING_LOGS_RATE",
            "samplingTracesRate" => "PROVIDE_SAMPLING_TRACES_RATE",
            "samplingMetricsRate" => "PROVIDE_SAMPLING_METRICS_RATE",
            "serviceName" => "PROVIDE_TELEMETRY_SERVICE_NAME",
            _ => continue,
        };
        unsafe { std::env::remove_var(env_key) };
    }

    if !into.is_empty() {
        variables.insert(
            into.to_string(),
            json!({ "raised": raised, "error": error }),
        );
    }
}

fn exec_bind_propagation(step: &Value, guards: &mut Guards) {
    let traceparent = step.get("traceparent").and_then(Value::as_str);
    let baggage = step.get("baggage").and_then(Value::as_str);

    let ctx = provide_telemetry::extract_w3c_context(traceparent, None, baggage);
    let guard = provide_telemetry::bind_propagation_context(ctx);
    guards._propagation = Some(guard);
}

fn exec_clear_propagation(guards: &mut Guards) {
    guards._propagation = None;
}

fn exec_get_trace_context(step: &Value, variables: &mut BTreeMap<String, Value>) {
    let into = as_str(step, "into");
    if into.is_empty() {
        return;
    }
    let ctx = provide_telemetry::get_trace_context();
    let trace_id = ctx
        .get("trace_id")
        .and_then(|v| v.as_ref())
        .cloned()
        .unwrap_or_default();
    let span_id = ctx
        .get("span_id")
        .and_then(|v| v.as_ref())
        .cloned()
        .unwrap_or_default();
    variables.insert(
        into.to_string(),
        json!({ "trace_id": trace_id, "span_id": span_id }),
    );
}

fn exec_bind_context(step: &Value, guards: &mut Guards) {
    let fields = as_object(step, "fields");
    let pairs: Vec<(String, Value)> = fields.into_iter().collect();
    let guard = provide_telemetry::bind_context(pairs);
    guards._context.push(guard);
}

fn exec_emit_log(step: &Value) {
    let message = as_str(step, "message");
    let logger = provide_telemetry::get_logger(Some("contract"));
    logger.info(message);
}

fn exec_capture_log(step: &Value, variables: &mut BTreeMap<String, Value>) {
    let into = as_str(step, "into");
    if into.is_empty() {
        return;
    }

    let raw = String::from_utf8(provide_telemetry::take_json_capture()).unwrap_or_default();

    // Parse the last JSON line from captured output.
    let mut record = Value::Null;
    for line in raw.lines().rev() {
        if let Ok(v) = serde_json::from_str::<Value>(line) {
            record = v;
            break;
        }
    }

    // Flatten the record into dotted variables for the harness.
    // The harness expects e.g. last_log.trace_id, last_log.span_id, etc.
    if let Value::Object(map) = &record {
        let mut flat = serde_json::Map::new();
        for (k, v) in map {
            // Convert to string for comparison (strip quotes from strings).
            match v {
                Value::String(s) => {
                    flat.insert(k.clone(), Value::String(s.clone()));
                }
                _ => {
                    flat.insert(k.clone(), v.clone());
                }
            }
        }
        variables.insert(into.to_string(), Value::Object(flat));
    } else {
        variables.insert(into.to_string(), record);
    }
}

fn exec_get_runtime_status(step: &Value, variables: &mut BTreeMap<String, Value>) {
    let into = as_str(step, "into");
    if into.is_empty() {
        return;
    }
    let status = provide_telemetry::get_runtime_status();
    let config = provide_telemetry::get_runtime_config();
    let service_name = config
        .as_ref()
        .map(|c| c.service_name.clone())
        .unwrap_or_default();
    variables.insert(
        into.to_string(),
        json!({
            "active": status.setup_done,
            "service_name": service_name,
            "setup_done": status.setup_done,
        }),
    );
}

fn run_case(case_id: &str, case: &Value) -> Value {
    let steps = case
        .get("steps")
        .and_then(Value::as_array)
        .expect("case must have steps array");

    let mut variables: BTreeMap<String, Value> = BTreeMap::new();
    let mut guards = Guards::new();

    // Ensure JSON log format so captured output is parseable.
    unsafe { std::env::set_var("PROVIDE_LOG_FORMAT", "json") };
    // Enable JSON capture before any log emission so we can capture output.
    provide_telemetry::enable_json_capture_for_tests();

    for step in steps {
        let op = as_str(step, "op");
        match op {
            "setup" => exec_setup(step),
            "setup_invalid" => exec_setup_invalid(step, &mut variables),
            "shutdown" => {
                provide_telemetry::shutdown_telemetry().ok();
            }
            "bind_propagation" => exec_bind_propagation(step, &mut guards),
            "clear_propagation" => exec_clear_propagation(&mut guards),
            "get_trace_context" => exec_get_trace_context(step, &mut variables),
            "bind_context" => exec_bind_context(step, &mut guards),
            "emit_log" => exec_emit_log(step),
            "capture_log" => exec_capture_log(step, &mut variables),
            "get_runtime_status" => exec_get_runtime_status(step, &mut variables),
            unknown => panic!("unsupported contract operation: '{unknown}'"),
        }
    }

    json!({ "case": case_id, "variables": variables })
}

fn main() {
    let case_id =
        std::env::var("PROVIDE_CONTRACT_CASE").expect("PROVIDE_CONTRACT_CASE env var required");

    let yaml_path = std::path::Path::new("../spec/contract_fixtures.yaml");
    let yaml_content = std::fs::read_to_string(yaml_path).unwrap_or_else(|_| {
        // Also try from the repo root (in case cwd is the repo root).
        std::fs::read_to_string("spec/contract_fixtures.yaml")
            .expect("cannot read spec/contract_fixtures.yaml")
    });

    let doc: Value = serde_yaml::from_str(&yaml_content).expect("failed to parse YAML");
    let cases = doc
        .get("contract_cases")
        .expect("YAML missing contract_cases key");
    let case = cases
        .get(&case_id)
        .unwrap_or_else(|| panic!("unknown contract case: {case_id}"));

    let result = run_case(&case_id, case);
    println!(
        "{}",
        serde_json::to_string(&result).expect("failed to serialize result")
    );
}
