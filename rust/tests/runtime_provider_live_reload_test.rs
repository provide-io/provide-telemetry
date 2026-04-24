// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
#![cfg(feature = "otel")]

use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};

use provide_telemetry::resilience::get_exporter_policy;
use provide_telemetry::sampling::Signal;
use provide_telemetry::{
    get_runtime_status, reload_runtime_from_env, setup_telemetry, shutdown_telemetry,
};

static ENV_LOCK: OnceLock<Mutex<()>> = OnceLock::new();
static RUNTIME_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

const ENV_KEYS: &[&str] = &[
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "PROVIDE_SAMPLING_LOGS_RATE",
    "PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS",
    "PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS",
    "PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS",
];

fn env_lock() -> &'static Mutex<()> {
    ENV_LOCK.get_or_init(|| Mutex::new(()))
}

fn runtime_lock() -> &'static Mutex<()> {
    RUNTIME_LOCK.get_or_init(|| Mutex::new(()))
}

fn restore_env(snapshot: &HashMap<String, Option<String>>) {
    for (key, value) in snapshot {
        match value {
            Some(value) => std::env::set_var(key, value),
            None => std::env::remove_var(key),
        }
    }
}

fn with_env(vars: &[(&str, &str)], test: impl FnOnce()) {
    let _guard = env_lock().lock().expect("env lock poisoned");
    let mut snapshot = HashMap::new();
    for key in ENV_KEYS {
        snapshot.insert((*key).to_string(), std::env::var(key).ok());
        std::env::remove_var(key);
    }
    for (key, value) in vars {
        snapshot.insert((*key).to_string(), std::env::var(key).ok());
        std::env::set_var(key, value);
    }

    test();

    restore_env(&snapshot);
}

fn reset_runtime() {
    let _ = shutdown_telemetry();
    provide_telemetry::otel::_reset_otel_for_tests();
}

#[test]
fn runtime_test_reload_runtime_from_env_preserves_timeout_fields_for_live_providers() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(
        &[
            ("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318"),
            ("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf"),
            ("PROVIDE_SAMPLING_LOGS_RATE", "1.0"),
            ("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS", "7.0"),
            ("PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS", "8.0"),
            ("PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS", "9.0"),
        ],
        || {
            reset_runtime();
            setup_telemetry().expect("setup should succeed");

            let status = get_runtime_status();
            assert!(status.providers.logs, "logs provider should be live");
            assert!(status.providers.traces, "traces provider should be live");
            assert!(status.providers.metrics, "metrics provider should be live");

            std::env::set_var("PROVIDE_SAMPLING_LOGS_RATE", "0.25");
            std::env::set_var("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS", "17.0");
            std::env::set_var("PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS", "18.0");
            std::env::set_var("PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS", "19.0");

            let reloaded = reload_runtime_from_env().expect("reload should succeed");
            assert_eq!(reloaded.sampling.logs_rate, 0.25);
            assert_eq!(reloaded.exporter.logs_timeout_seconds, 7.0);
            assert_eq!(reloaded.exporter.traces_timeout_seconds, 8.0);
            assert_eq!(reloaded.exporter.metrics_timeout_seconds, 9.0);

            let logs_policy = get_exporter_policy(Signal::Logs).expect("logs policy should exist");
            let traces_policy =
                get_exporter_policy(Signal::Traces).expect("traces policy should exist");
            let metrics_policy =
                get_exporter_policy(Signal::Metrics).expect("metrics policy should exist");
            assert_eq!(logs_policy.timeout_seconds, 7.0);
            assert_eq!(traces_policy.timeout_seconds, 8.0);
            assert_eq!(metrics_policy.timeout_seconds, 9.0);
        },
    );
}
