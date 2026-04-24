use super::*;

use std::collections::HashMap;

const ENV_KEYS: &[&str] = &[
    "PROVIDE_TELEMETRY_SERVICE_NAME",
    "PROVIDE_TELEMETRY_ENV",
    "PROVIDE_TELEMETRY_VERSION",
    "PROVIDE_TRACE_ENABLED",
    "PROVIDE_METRICS_ENABLED",
    "PROVIDE_SAMPLING_LOGS_RATE",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS",
    "PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS",
    "PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS",
    "PROVIDE_LOG_INCLUDE_TIMESTAMP",
];

fn with_env(vars: &[(&str, &str)], test: impl FnOnce()) {
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

    for (key, value) in snapshot {
        match value {
            Some(value) => std::env::set_var(key, value),
            None => std::env::remove_var(key),
        }
    }
}

#[test]
fn runtime_test_provider_config_changed_detects_each_provider_field() {
    let current = TelemetryConfig::default();

    let mut changed = current.clone();
    changed.service_name = "svc-2".to_string();
    assert!(provider_config_changed(&current, &changed));

    let mut changed = current.clone();
    changed.environment = "prod".to_string();
    assert!(provider_config_changed(&current, &changed));

    let mut changed = current.clone();
    changed.version = "1.2.3".to_string();
    assert!(provider_config_changed(&current, &changed));

    let mut changed = current.clone();
    changed.logging.otlp_headers.insert("x".into(), "1".into());
    assert!(provider_config_changed(&current, &changed));

    let mut changed = current.clone();
    changed.tracing.enabled = !changed.tracing.enabled;
    assert!(provider_config_changed(&current, &changed));

    let mut changed = current.clone();
    changed.metrics.enabled = !changed.metrics.enabled;
    assert!(provider_config_changed(&current, &changed));

    let mut changed = current.clone();
    changed.logging.otlp_endpoint = Some("http://other:4318".into());
    assert!(provider_config_changed(&current, &changed));

    let mut changed = current.clone();
    changed.tracing.otlp_endpoint = Some("http://other:4318".into());
    assert!(provider_config_changed(&current, &changed));

    let mut changed = current.clone();
    changed.metrics.otlp_endpoint = Some("http://other:4318".into());
    assert!(provider_config_changed(&current, &changed));

    let mut changed = current.clone();
    changed
        .tracing
        .otlp_headers
        .insert("auth".into(), "tok".into());
    assert!(provider_config_changed(&current, &changed));

    let mut changed = current.clone();
    changed
        .metrics
        .otlp_headers
        .insert("auth".into(), "tok".into());
    assert!(provider_config_changed(&current, &changed));

    let mut changed = current.clone();
    changed.logging.otlp_protocol = "http/json".to_string();
    assert!(provider_config_changed(&current, &changed));

    let mut changed = current.clone();
    changed.tracing.otlp_protocol = "http/json".to_string();
    assert!(provider_config_changed(&current, &changed));

    let mut changed = current.clone();
    changed.metrics.otlp_protocol = "http/json".to_string();
    assert!(provider_config_changed(&current, &changed));

    let mut changed = current.clone();
    changed.exporter.logs_timeout_seconds = 5.0;
    assert!(provider_config_changed(&current, &changed));

    let mut changed = current.clone();
    changed.exporter.traces_timeout_seconds = 5.0;
    assert!(provider_config_changed(&current, &changed));

    let mut changed = current.clone();
    changed.exporter.metrics_timeout_seconds = 5.0;
    assert!(provider_config_changed(&current, &changed));

    let mut changed = current.clone();
    changed.metrics.metric_export_interval_ms = 30_000;
    assert!(provider_config_changed(&current, &changed));
}

#[test]
fn runtime_test_provider_config_changed_is_false_for_hot_only_changes() {
    let current = TelemetryConfig::default();
    let mut changed = current.clone();
    changed.sampling.logs_rate = 0.25;
    changed.backpressure.logs_maxsize = 9;
    changed.exporter.logs_retries = 2;
    changed.security.max_attr_count = 99;
    changed.slo.enable_red_metrics = !changed.slo.enable_red_metrics;
    changed.pii_max_depth = 3;
    changed.strict_schema = true;

    assert!(!provider_config_changed(&current, &changed));
}

#[test]
fn runtime_test_per_signal_helpers_are_independent() {
    let base = TelemetryConfig::default();

    let mut changed = base.clone();
    changed.logging.otlp_protocol = "http/json".to_string();
    assert!(logging_provider_config_changed(&base, &changed));
    assert!(!tracing_provider_config_changed(&base, &changed));
    assert!(!metrics_provider_config_changed(&base, &changed));

    let mut changed = base.clone();
    changed.exporter.traces_timeout_seconds = 5.0;
    assert!(!logging_provider_config_changed(&base, &changed));
    assert!(tracing_provider_config_changed(&base, &changed));
    assert!(!metrics_provider_config_changed(&base, &changed));

    let mut changed = base.clone();
    changed.metrics.metric_export_interval_ms = 30_000;
    assert!(!logging_provider_config_changed(&base, &changed));
    assert!(!tracing_provider_config_changed(&base, &changed));
    assert!(metrics_provider_config_changed(&base, &changed));
}

#[test]
fn runtime_test_reload_timeout_hot_when_no_provider_snapshot_matches_live_policy() {
    let _guard = crate::testing::acquire_test_state_lock();
    crate::testing::reset_telemetry_state();

    with_env(
        &[
            ("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS", "7.0"),
            ("PROVIDE_SAMPLING_LOGS_RATE", "1.0"),
        ],
        || {
            set_active_config(Some(
                TelemetryConfig::from_env().expect("config must parse"),
            ));
            apply_policies(&get_runtime_config().expect("config must exist"));

            std::env::set_var("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS", "99.0");
            std::env::set_var("PROVIDE_SAMPLING_LOGS_RATE", "0.5");

            let reloaded = reload_runtime_from_env().expect("reload must succeed");
            assert_eq!(reloaded.exporter.logs_timeout_seconds, 99.0);

            let policy = crate::resilience::get_exporter_policy(crate::sampling::Signal::Logs)
                .expect("policy must exist");
            assert_eq!(
                policy.timeout_seconds,
                reloaded.exporter.logs_timeout_seconds
            );
            assert_eq!(reloaded.sampling.logs_rate, 0.5);
        },
    );

    crate::testing::reset_telemetry_state();
}

#[test]
fn runtime_test_runtime_config_snapshot_reports_cfg_and_setup_done_from_one_read() {
    let _guard = crate::testing::acquire_test_state_lock();
    crate::testing::reset_telemetry_state();
    set_active_config(None);
    let (cfg, setup_done) = runtime_config_snapshot();
    assert!(cfg.is_none());
    assert!(!setup_done);

    let configured = TelemetryConfig::default();
    set_active_config(Some(configured.clone()));
    let (cfg, setup_done) = runtime_config_snapshot();
    assert_eq!(cfg, Some(configured));
    assert!(setup_done);

    crate::testing::reset_telemetry_state();
}

#[test]
fn runtime_test_update_runtime_config_requires_setup_in_unit_module() {
    let _guard = crate::testing::acquire_test_state_lock();
    crate::testing::reset_telemetry_state();

    let err = update_runtime_config(RuntimeOverrides::default())
        .expect_err("update before setup must fail");
    assert!(err.message.contains("setup_telemetry"));
}

#[test]
fn runtime_test_update_runtime_config_preserves_fields_not_overridden() {
    let _guard = crate::testing::acquire_test_state_lock();
    crate::testing::reset_telemetry_state();

    let current = TelemetryConfig {
        sampling: crate::SamplingConfig {
            logs_rate: 0.25,
            traces_rate: 0.5,
            metrics_rate: 0.75,
        },
        backpressure: crate::BackpressureConfig {
            logs_maxsize: 1,
            traces_maxsize: 2,
            metrics_maxsize: 3,
        },
        ..TelemetryConfig::default()
    };
    set_active_config(Some(current));

    let updated = update_runtime_config(RuntimeOverrides {
        sampling: None,
        backpressure: Some(crate::BackpressureConfig {
            logs_maxsize: 9,
            traces_maxsize: 8,
            metrics_maxsize: 7,
        }),
        exporter: None,
        security: None,
        slo: None,
        pii_max_depth: None,
        strict_schema: None,
        event_schema: None,
        logging: None,
    })
    .expect("partial update must succeed");

    assert_eq!(updated.sampling.logs_rate, 0.25);
    assert_eq!(updated.sampling.traces_rate, 0.5);
    assert_eq!(updated.sampling.metrics_rate, 0.75);
    assert_eq!(updated.backpressure.logs_maxsize, 9);
    assert_eq!(updated.backpressure.traces_maxsize, 8);
    assert_eq!(updated.backpressure.metrics_maxsize, 7);

    crate::testing::reset_telemetry_state();
}

#[test]
fn runtime_test_reload_runtime_from_env_covers_parse_and_drift_paths_in_unit_module() {
    let _guard = crate::testing::acquire_test_state_lock();
    crate::testing::reset_telemetry_state();
    set_active_config(None);

    let err = reload_runtime_from_env().expect_err("reload before setup must fail");
    assert!(err.message.contains("setup_telemetry"));

    with_env(
        &[
            ("PROVIDE_TELEMETRY_SERVICE_NAME", "reloaded-service"),
            ("PROVIDE_TELEMETRY_ENV", "prod"),
            ("PROVIDE_TELEMETRY_VERSION", "2.0.0"),
            ("PROVIDE_TRACE_ENABLED", "true"),
            ("PROVIDE_METRICS_ENABLED", "true"),
            ("PROVIDE_SAMPLING_LOGS_RATE", "1.0"),
        ],
        || {
            let current = TelemetryConfig {
                service_name: "initial-service".to_string(),
                environment: "dev".to_string(),
                version: "1.0.0".to_string(),
                tracing: crate::TracingConfig {
                    enabled: true,
                    ..TelemetryConfig::default().tracing
                },
                metrics: crate::MetricsConfig {
                    enabled: true,
                    ..TelemetryConfig::default().metrics
                },
                ..TelemetryConfig::default()
            };
            set_active_config(Some(current));
            apply_policies(&get_runtime_config().expect("config must exist"));

            std::env::set_var("PROVIDE_TRACE_ENABLED", "false");
            std::env::set_var("PROVIDE_METRICS_ENABLED", "false");
            std::env::set_var("PROVIDE_SAMPLING_LOGS_RATE", "0.5");

            let reloaded = reload_runtime_from_env().expect("reload should succeed");
            assert_eq!(reloaded.service_name, "initial-service");
            assert_eq!(reloaded.environment, "dev");
            assert_eq!(reloaded.version, "1.0.0");
            assert!(reloaded.tracing.enabled);
            assert!(reloaded.metrics.enabled);
            assert_eq!(reloaded.sampling.logs_rate, 0.5);
        },
    );

    with_env(&[("PROVIDE_LOG_INCLUDE_TIMESTAMP", "not-a-bool")], || {
        set_active_config(Some(TelemetryConfig::default()));
        let err = reload_runtime_from_env().expect_err("invalid env must fail reload");
        assert!(err.message.contains("PROVIDE_LOG_INCLUDE_TIMESTAMP"));
    });

    crate::testing::reset_telemetry_state();
}

#[cfg(feature = "otel")]
#[test]
fn runtime_test_reload_timeout_stays_frozen_when_provider_snapshot_is_live() {
    let _guard = crate::testing::acquire_test_state_lock();
    let _ = crate::shutdown_telemetry();
    crate::testing::reset_telemetry_state();
    crate::otel::_reset_otel_for_tests();

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
            crate::setup_telemetry().expect("setup should succeed");
            let status = crate::get_runtime_status();
            assert!(status.providers.logs);
            assert!(status.providers.traces);
            assert!(status.providers.metrics);

            std::env::set_var("PROVIDE_SAMPLING_LOGS_RATE", "0.25");
            std::env::set_var("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS", "17.0");
            std::env::set_var("PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS", "18.0");
            std::env::set_var("PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS", "19.0");

            let reloaded = reload_runtime_from_env().expect("reload must succeed");
            assert_eq!(reloaded.sampling.logs_rate, 0.25);
            assert_eq!(reloaded.exporter.logs_timeout_seconds, 7.0);
            assert_eq!(reloaded.exporter.traces_timeout_seconds, 8.0);
            assert_eq!(reloaded.exporter.metrics_timeout_seconds, 9.0);
        },
    );

    let _ = crate::shutdown_telemetry();
    crate::testing::reset_telemetry_state();
    crate::otel::_reset_otel_for_tests();
}
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
