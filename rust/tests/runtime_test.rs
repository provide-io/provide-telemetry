// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
mod runtime_test_support;

use provide_telemetry::{
    get_runtime_status, reconfigure_telemetry, reload_runtime_from_env, setup_telemetry,
    shutdown_telemetry, update_runtime_config, BackpressureConfig, ExporterPolicyConfig,
    ProviderMode, RuntimeOverrides, RuntimeState, SLOConfig, SamplingConfig, SecurityConfig,
    SignalFlushResult, TelemetryConfig, TelemetryRuntime,
};
use runtime_test_support::*;

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
        setup_telemetry(None).expect("setup should succeed");

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

        let first = setup_telemetry(None).expect("first setup should succeed");
        let second = setup_telemetry(None).expect("second setup should succeed");

        assert_eq!(first.service_name, second.service_name);
        assert!(provide_telemetry::get_runtime_config().is_some());
    });
}

#[test]
fn runtime_test_get_runtime_config_returns_defensive_copy() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(&[], || {
        reset_runtime();
        setup_telemetry(None).expect("setup should succeed");

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
        setup_telemetry(None).expect("setup should succeed");

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
                logs_shutdown_timeout_seconds: 5.0,
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
            logging: None,
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
            let initial = setup_telemetry(None).expect("setup should succeed");
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
        setup_telemetry(None).expect("setup should succeed");

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
        setup_telemetry(None).expect("setup should succeed");

        shutdown_telemetry(None).expect("shutdown should succeed");

        assert!(provide_telemetry::get_runtime_config().is_none());
    });
}

#[test]
fn runtime_test_update_runtime_config_requires_setup() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(&[], || {
        reset_runtime();

        let err = update_runtime_config(RuntimeOverrides::default())
            .expect_err("update before setup must fail");
        assert!(err.message.contains("setup_telemetry"));
    });
}

#[test]
fn runtime_test_reload_runtime_from_env_requires_setup_and_surfaces_parse_errors() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(&[], || {
        reset_runtime();

        let err = reload_runtime_from_env().expect_err("reload before setup must fail");
        assert!(err.message.contains("setup_telemetry"));
    });

    with_env(&[], || {
        reset_runtime();
        setup_telemetry(None).expect("setup should succeed");
        std::env::set_var("PROVIDE_LOG_INCLUDE_TIMESTAMP", "not-a-bool");

        let err = reload_runtime_from_env().expect_err("invalid env must fail reload");
        assert!(err.message.contains("PROVIDE_LOG_INCLUDE_TIMESTAMP"));
        std::env::remove_var("PROVIDE_LOG_INCLUDE_TIMESTAMP");
    });
}

/// With no OTel providers installed, every signal reports not_installed.
///
/// `flushed` is deliberately *not* asserted equal to `installed` any more: a
/// signal reported installed without a provider of ours behind it is not_owned,
/// because we do not drain a provider the host put on the OTel globals.
fn assert_flush_result_matches_provider(installed: bool, result: SignalFlushResult) {
    assert_eq!(result.not_installed, !installed);
    if installed {
        assert!(
            result.flushed || result.not_owned,
            "an installed signal must report a drain outcome or not_owned: {result:?}"
        );
    } else {
        assert!(!result.flushed);
        assert!(!result.not_owned);
        assert!(!result.timed_out);
    }
    assert!(!result.failed);
}

#[test]
fn runtime_object_test_complete_successful_lifecycle() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(&[], || {
        reset_runtime();
        let mut runtime = TelemetryRuntime::default();

        assert_eq!(runtime.provider_mode(), ProviderMode::Owned);
        assert_eq!(runtime.state(), RuntimeState::Ready);
        assert!(runtime.get_runtime_config().is_none());
        assert!(!runtime.get_runtime_status().setup_done);
        assert_eq!(
            runtime.get_logger(Some("runtime.logger")).target(),
            "runtime.logger"
        );
        assert_eq!(
            runtime.get_tracer(Some("runtime.tracer")).name(),
            "runtime.tracer"
        );
        assert_eq!(
            runtime.get_meter(Some("runtime.meter")).name(),
            "runtime.meter"
        );

        let started = runtime.start(None).expect("runtime start should succeed");
        assert_eq!(runtime.state(), RuntimeState::Ready);
        assert_eq!(runtime.get_runtime_config(), Some(started.clone()));
        let status = runtime.get_runtime_status();
        assert!(status.setup_done);

        let flushed = runtime.flush(None).expect("runtime flush should succeed");
        assert_flush_result_matches_provider(status.providers.logs, flushed.logs);
        assert_flush_result_matches_provider(status.providers.traces, flushed.traces);
        assert_flush_result_matches_provider(status.providers.metrics, flushed.metrics);

        let update = runtime.update_config(RuntimeOverrides {
            strict_schema: Some(!started.strict_schema),
            ..RuntimeOverrides::default()
        });
        assert!(update.applied);
        assert_eq!(update.previous, Some(started));
        assert_eq!(
            update.current.as_ref().map(|cfg| cfg.strict_schema),
            Some(
                !update
                    .previous
                    .as_ref()
                    .expect("previous config")
                    .strict_schema
            )
        );
        assert!(update.error.is_none());
        assert_eq!(update.state, RuntimeState::Ready);

        let current = update.current.expect("updated config");
        assert_eq!(
            runtime
                .reconfigure(Some(current.clone()))
                .expect("explicit reconfigure"),
            current
        );
        assert_eq!(
            runtime.reconfigure(None).expect("environment reconfigure"),
            TelemetryConfig::from_env().expect("default environment config")
        );

        runtime
            .shutdown(None)
            .expect("runtime shutdown should succeed");
        assert_eq!(runtime.state(), RuntimeState::Stopped);
        assert!(runtime.get_runtime_config().is_none());
    });
}

#[test]
fn runtime_object_test_failed_start_is_degraded_and_update_reports_error() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(&[("PROVIDE_LOG_INCLUDE_TIMESTAMP", "not-a-bool")], || {
        reset_runtime();
        let mut runtime = TelemetryRuntime::new();

        let err = runtime
            .start(None)
            .expect_err("invalid config must fail start");
        assert!(err.message.contains("PROVIDE_LOG_INCLUDE_TIMESTAMP"));
        assert_eq!(runtime.state(), RuntimeState::Degraded);

        let update = runtime.update_config(RuntimeOverrides::default());
        assert!(!update.applied);
        assert!(update.previous.is_none());
        assert!(update.current.is_none());
        assert!(update
            .error
            .as_deref()
            .is_some_and(|message| message.contains("setup_telemetry")));
        assert_eq!(update.state, RuntimeState::Degraded);
    });
}

#[test]
fn runtime_object_test_reconfigure_from_invalid_environment_returns_error() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(&[("PROVIDE_LOG_INCLUDE_TIMESTAMP", "not-a-bool")], || {
        reset_runtime();
        let mut runtime = TelemetryRuntime::new();

        let err = runtime
            .reconfigure(None)
            .expect_err("invalid environment must fail reconfigure");
        assert!(err.message.contains("PROVIDE_LOG_INCLUDE_TIMESTAMP"));
        assert_eq!(runtime.state(), RuntimeState::Ready);
    });
}

/// A signal drains, or reports why it did not — one aggregate must not stand in
/// for all three, and an adopted provider must not be reported as flushed.
#[test]
fn runtime_object_test_flush_reports_each_signal_on_its_own() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(&[], || {
        reset_runtime();
        let mut runtime = TelemetryRuntime::default();
        runtime.start(None).expect("runtime start should succeed");

        let result = runtime.flush(None).expect("flush should succeed");

        // Nothing installed in this build: each signal says so, and no signal
        // claims to have flushed records it never had.
        for signal in [&result.logs, &result.traces, &result.metrics] {
            assert!(signal.not_installed, "expected not_installed: {signal:?}");
            assert!(!signal.flushed);
            assert!(!signal.not_owned);
            assert!(!signal.timed_out);
            assert!(!signal.failed);
        }
    });
}

/// A caller-supplied deadline reaches the drain without panicking, whatever it
/// holds — `Duration::from_secs_f64` rejects NaN and infinity.
#[test]
fn runtime_object_test_flush_survives_a_non_finite_deadline() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(&[], || {
        reset_runtime();
        let mut runtime = TelemetryRuntime::default();
        runtime.start(None).expect("runtime start should succeed");

        for deadline in [f64::NAN, f64::INFINITY, 0.0, -1.0, f64::MAX] {
            runtime
                .flush(Some(deadline))
                .unwrap_or_else(|err| panic!("flush({deadline}) failed: {err:?}"));
        }
    });
}
