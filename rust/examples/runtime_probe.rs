// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

use serde_json::{json, Value};

fn capture_record(message: &str) -> Value {
    provide_telemetry::enable_json_capture_for_tests();
    let _guard = provide_telemetry::set_trace_context(
        Some("0af7651916cd43dd8448eb211c80319c".to_string()),
        Some("b7ad6b7169203331".to_string()),
    );
    provide_telemetry::get_logger(Some("probe")).info(message);
    let output = String::from_utf8(provide_telemetry::take_json_capture()).expect("utf8 output");
    for line in output.lines() {
        if let Ok(value) = serde_json::from_str::<Value>(line) {
            return value;
        }
    }
    panic!("no JSON object found in output: {output:?}");
}

fn main() {
    let case = std::env::var("PROVIDE_PARITY_PROBE_CASE").expect("probe case");
    let result = match case.as_str() {
        "lazy_init_logger" => json!({
            "case": case,
            "record": capture_record("log.output.parity"),
        }),
        "strict_schema_rejection" => {
            provide_telemetry::setup_telemetry().expect("setup");
            let record = capture_record("Bad.Event.Ok");
            provide_telemetry::shutdown_telemetry().expect("shutdown");
            json!({
                "case": case,
                "emitted": true,
                "schema_error": record.get("_schema_error").is_some(),
            })
        }
        "required_keys_rejection" => {
            provide_telemetry::setup_telemetry().expect("setup");
            let record = capture_record("user.auth.ok");
            provide_telemetry::shutdown_telemetry().expect("shutdown");
            json!({
                "case": case,
                "emitted": true,
                "schema_error": record.get("_schema_error").is_some(),
            })
        }
        "invalid_config" => json!({
            "case": case,
            "raised": provide_telemetry::setup_telemetry().is_err(),
        }),
        "fail_open_exporter_init" => {
            provide_telemetry::setup_telemetry().expect("setup");
            let status = provide_telemetry::get_runtime_status();
            provide_telemetry::shutdown_telemetry().expect("shutdown");
            json!({
                "case": case,
                "setup_done": status.setup_done,
                "providers_cleared": !status.providers.logs && !status.providers.traces && !status.providers.metrics,
                "fallback_all": status.fallback.logs && status.fallback.traces && status.fallback.metrics,
            })
        }
        "shutdown_re_setup" => {
            provide_telemetry::setup_telemetry().expect("first setup");
            let first = provide_telemetry::get_runtime_status();
            provide_telemetry::shutdown_telemetry().expect("shutdown");
            let second = provide_telemetry::get_runtime_status();
            provide_telemetry::setup_telemetry().expect("second setup");
            let third = provide_telemetry::get_runtime_status();
            provide_telemetry::shutdown_telemetry().expect("shutdown");
            json!({
                "case": case,
                "first_setup_done": first.setup_done,
                "shutdown_cleared_setup": !second.setup_done,
                "re_setup_done": third.setup_done,
                "signals_match": first.signals == third.signals,
                "providers_match": first.providers == third.providers,
            })
        }
        _ => panic!("unknown case: {case}"),
    };
    println!(
        "{}",
        serde_json::to_string(&result).expect("serialize result")
    );
}
