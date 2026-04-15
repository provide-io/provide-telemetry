// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};

use provide_telemetry::{
    get_runtime_status, reconfigure_telemetry, reload_runtime_from_env, setup_telemetry,
    shutdown_telemetry, update_runtime_config, BackpressureConfig, ExporterPolicyConfig,
    RuntimeOverrides, SLOConfig, SamplingConfig, SecurityConfig, TelemetryConfig,
};

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

fn reset_runtime() {
    let _ = shutdown_telemetry();
    provide_telemetry::otel::_reset_otel_for_tests();
}

#[test]
fn runtime_test_get_runtime_config_none_before_setup() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(&[], || {
        reset_runtime();
        assert!(provide_telemetry::get_runtime_config().is_none());
    });
}

#[test]
fn runtime_test_get_runtime_status_before_setup_uses_fallback() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(&[], || {
        reset_runtime();

        let status = get_runtime_status();

        assert!(!status.setup_done);
        assert!(!status.providers.logs);
        assert!(!status.providers.traces);
        assert!(!status.providers.metrics);
        assert!(status.fallback.logs);
        assert!(status.fallback.traces);
        assert!(status.fallback.metrics);
    });
}

#[test]
fn runtime_test_get_runtime_status_after_setup_reports_signal_enablement() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(&[], || {
        reset_runtime();
        setup_telemetry().expect("setup should succeed");

        let status = get_runtime_status();

        assert!(status.setup_done);
        assert!(status.signals.logs);
        assert!(status.signals.traces);
        assert!(status.signals.metrics);
        assert!(status.fallback.logs);
        assert!(status.fallback.traces);
        assert!(status.fallback.metrics);
    });
}

#[test]
fn runtime_test_setup_is_idempotent() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(&[], || {
        reset_runtime();

        let first = setup_telemetry().expect("first setup should succeed");
        let second = setup_telemetry().expect("second setup should succeed");

        assert_eq!(first.service_name, second.service_name);
        assert!(provide_telemetry::get_runtime_config().is_some());
    });
}

#[test]
fn runtime_test_get_runtime_config_returns_defensive_copy() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(&[], || {
        reset_runtime();
        setup_telemetry().expect("setup should succeed");

        let mut local = provide_telemetry::get_runtime_config().expect("config should exist");
        local.service_name = "mutated-locally".to_string();

        let again = provide_telemetry::get_runtime_config().expect("config should still exist");
        assert_ne!(again.service_name, "mutated-locally");
    });
}

#[test]
fn runtime_test_update_runtime_config_applies_hot_fields() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(&[], || {
        reset_runtime();
        setup_telemetry().expect("setup should succeed");

        let updated = update_runtime_config(RuntimeOverrides {
            sampling: Some(SamplingConfig {
                logs_rate: 0.25,
                traces_rate: 1.0,
                metrics_rate: 1.0,
            }),
            backpressure: Some(BackpressureConfig {
                logs_maxsize: 9,
                traces_maxsize: 0,
                metrics_maxsize: 0,
            }),
            exporter: Some(ExporterPolicyConfig {
                logs_retries: 2,
                traces_retries: 0,
                metrics_retries: 0,
                logs_backoff_seconds: 0.5,
                traces_backoff_seconds: 0.0,
                metrics_backoff_seconds: 0.0,
                logs_timeout_seconds: 7.5,
                traces_timeout_seconds: 10.0,
                metrics_timeout_seconds: 10.0,
                logs_fail_open: false,
                traces_fail_open: true,
                metrics_fail_open: true,
            }),
            security: Some(SecurityConfig {
                max_attr_value_length: 2048,
                max_attr_count: 32,
                max_nesting_depth: 8,
            }),
            slo: Some(SLOConfig {
                enable_red_metrics: true,
                enable_use_metrics: false,
            }),
            pii_max_depth: Some(3),
            strict_schema: Some(true),
            event_schema: None,
        })
        .expect("update should succeed");

        assert_eq!(updated.sampling.logs_rate, 0.25);
        assert_eq!(updated.backpressure.logs_maxsize, 9);
        assert_eq!(updated.exporter.logs_retries, 2);
        assert_eq!(updated.security.max_attr_value_length, 2048);
        assert!(updated.slo.enable_red_metrics);
        assert_eq!(updated.pii_max_depth, 3);
        assert!(updated.strict_schema);
    });
}

#[test]
fn runtime_test_reload_runtime_from_env_preserves_cold_fields_and_updates_hot_fields() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(
        &[
            ("PROVIDE_TELEMETRY_SERVICE_NAME", "initial-service"),
            ("PROVIDE_SAMPLING_LOGS_RATE", "1.0"),
        ],
        || {
            reset_runtime();
            let initial = setup_telemetry().expect("setup should succeed");
            assert_eq!(initial.service_name, "initial-service");

            std::env::set_var("PROVIDE_TELEMETRY_SERVICE_NAME", "reloaded-service");
            std::env::set_var("PROVIDE_SAMPLING_LOGS_RATE", "0.5");

            let reloaded = reload_runtime_from_env().expect("reload should succeed");
            assert_eq!(reloaded.service_name, "initial-service");
            assert_eq!(reloaded.sampling.logs_rate, 0.5);
        },
    );
}

#[test]
fn runtime_test_reconfigure_telemetry_applies_cold_fields() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(&[], || {
        reset_runtime();

        #[cfg(not(feature = "otel"))]
        setup_telemetry().expect("setup should succeed");

        let target = TelemetryConfig {
            service_name: "reconfigured-service".to_string(),
            environment: "prod".to_string(),
            ..TelemetryConfig::default()
        };

        let updated = reconfigure_telemetry(Some(target)).expect("reconfigure should succeed");
        assert_eq!(updated.service_name, "reconfigured-service");
        assert_eq!(updated.environment, "prod");
    });
}

#[test]
fn runtime_test_shutdown_clears_setup_state() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(&[], || {
        reset_runtime();
        setup_telemetry().expect("setup should succeed");

        shutdown_telemetry().expect("shutdown should succeed");

        assert!(provide_telemetry::get_runtime_config().is_none());
    });
}

#[test]
fn runtime_test_update_runtime_config_reapplies_runtime_policies() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(&[], || {
        reset_runtime();
        setup_telemetry().expect("setup should succeed");

        update_runtime_config(RuntimeOverrides {
            sampling: Some(SamplingConfig {
                logs_rate: 0.25,
                traces_rate: 1.0,
                metrics_rate: 1.0,
            }),
            backpressure: Some(BackpressureConfig {
                logs_maxsize: 17,
                traces_maxsize: 0,
                metrics_maxsize: 0,
            }),
            exporter: Some(ExporterPolicyConfig {
                logs_retries: 2,
                logs_backoff_seconds: 1.5,
                logs_timeout_seconds: 22.0,
                logs_fail_open: false,
                traces_retries: 0,
                traces_backoff_seconds: 0.0,
                traces_timeout_seconds: 10.0,
                traces_fail_open: true,
                metrics_retries: 0,
                metrics_backoff_seconds: 0.0,
                metrics_timeout_seconds: 10.0,
                metrics_fail_open: true,
            }),
            security: None,
            slo: None,
            pii_max_depth: None,
            strict_schema: None,
            event_schema: None,
        })
        .expect("update should succeed");

    // Verify live sampling policy
    let sp =
        provide_telemetry::sampling::get_sampling_policy(provide_telemetry::sampling::Signal::Logs)
            .expect("sampling policy should exist");
    assert_eq!(sp.default_rate, 0.25, "sampling policy not updated live");

        // Verify live queue policy
        let qp = provide_telemetry::get_queue_policy();
        assert_eq!(qp.logs_maxsize, 17, "queue policy not updated live");

    // Verify live exporter policy
    let ep = provide_telemetry::resilience::get_exporter_policy(
        provide_telemetry::sampling::Signal::Logs,
    )
    .expect("exporter policy should exist");
    assert_eq!(ep.retries, 2, "exporter policy not updated live");
    assert_eq!(ep.backoff_seconds, 1.5, "exporter backoff not updated live");
    assert_eq!(
        ep.timeout_seconds, 22.0,
        "exporter timeout not updated live"
    );
    assert!(!ep.fail_open, "exporter fail_open not updated live");
}

#[test]
fn runtime_test_reload_runtime_from_env_reapplies_runtime_policies() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(&[("PROVIDE_SAMPLING_LOGS_RATE", "1.0")], || {
        reset_runtime();
        setup_telemetry().expect("setup should succeed");

        std::env::set_var("PROVIDE_SAMPLING_LOGS_RATE", "0.33");

        reload_runtime_from_env().expect("reload should succeed");

        let sp = provide_telemetry::sampling::get_sampling_policy(
            provide_telemetry::sampling::Signal::Logs,
        )
        .expect("sampling policy should exist");
        assert_eq!(
            sp.default_rate, 0.33,
            "sampling policy not updated after env reload"
        );
    });
}

#[test]
fn runtime_test_reconfigure_telemetry_reapplies_runtime_policies() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    reset_runtime();
    setup_telemetry().expect("setup should succeed");

    let target = TelemetryConfig {
        sampling: SamplingConfig {
            logs_rate: 0.42,
            traces_rate: 1.0,
            metrics_rate: 1.0,
        },
        backpressure: BackpressureConfig {
            logs_maxsize: 23,
            traces_maxsize: 0,
            metrics_maxsize: 0,
        },
        ..TelemetryConfig::default()
    };

    reconfigure_telemetry(Some(target)).expect("reconfigure should succeed");

    let sp =
        provide_telemetry::sampling::get_sampling_policy(provide_telemetry::sampling::Signal::Logs)
            .expect("sampling policy should exist");
    assert_eq!(
        sp.default_rate, 0.42,
        "sampling policy not updated live after reconfigure"
    );

    let qp = provide_telemetry::get_queue_policy();
    assert_eq!(
        qp.logs_maxsize, 23,
        "queue policy not updated live after reconfigure"
    );
}
