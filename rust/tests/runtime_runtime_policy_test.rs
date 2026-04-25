// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
mod runtime_test_support;

use provide_telemetry::{
    reconfigure_telemetry, reload_runtime_from_env, setup_telemetry, update_runtime_config,
    BackpressureConfig, ExporterPolicyConfig, RuntimeOverrides, SamplingConfig, TelemetryConfig,
};
use runtime_test_support::*;

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
            logging: None,
        })
        .expect("update should succeed");

        let sp = provide_telemetry::sampling::get_sampling_policy(
            provide_telemetry::sampling::Signal::Logs,
        )
        .expect("sampling policy should exist");
        assert_eq!(sp.default_rate, 0.25, "sampling policy not updated live");

        let qp = provide_telemetry::get_queue_policy();
        assert_eq!(qp.logs_maxsize, 17, "queue policy not updated live");

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
    });
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
    with_env(&[], || {
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

        let sp = provide_telemetry::sampling::get_sampling_policy(
            provide_telemetry::sampling::Signal::Logs,
        )
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
    });
}
