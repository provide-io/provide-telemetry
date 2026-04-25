// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};

use provide_telemetry::shutdown_telemetry;

static ENV_LOCK: OnceLock<Mutex<()>> = OnceLock::new();
static RUNTIME_LOCK: OnceLock<Mutex<()>> = OnceLock::new();
const PROVIDER_ENV_KEYS: &[&str] = &[
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_HEADERS",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
    "OTEL_EXPORTER_OTLP_LOGS_HEADERS",
    "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
    "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
    "OTEL_EXPORTER_OTLP_METRICS_HEADERS",
    "OTEL_EXPORTER_OTLP_METRICS_PROTOCOL",
];

pub fn env_lock() -> &'static Mutex<()> {
    ENV_LOCK.get_or_init(|| Mutex::new(()))
}

pub fn runtime_lock() -> &'static Mutex<()> {
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

pub fn with_env(vars: &[(&str, &str)], test: impl FnOnce()) {
    let _guard = env_lock().lock().expect("env lock poisoned");
    let mut snapshot = HashMap::new();
    for key in PROVIDER_ENV_KEYS {
        snapshot.insert((*key).to_string(), std::env::var(key).ok());
    }
    for (key, _) in vars {
        snapshot.insert((*key).to_string(), std::env::var(key).ok());
    }
    for key in PROVIDER_ENV_KEYS {
        std::env::remove_var(key);
    }
    for (key, value) in vars {
        std::env::set_var(key, value);
    }

    test();

    restore_env(&snapshot);
}

pub fn reset_runtime() {
    let _ = shutdown_telemetry();
    provide_telemetry::otel::_reset_otel_for_tests();
}
