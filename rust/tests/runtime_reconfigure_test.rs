// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
mod runtime_test_support;

use provide_telemetry::{reconfigure_telemetry, reload_runtime_from_env, setup_telemetry};
use runtime_test_support::*;

#[test]
fn runtime_test_reload_runtime_from_env_warns_for_all_cold_field_drift() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(
        &[
            ("PROVIDE_TELEMETRY_SERVICE_NAME", "initial-service"),
            ("PROVIDE_TELEMETRY_ENV", "dev"),
            ("PROVIDE_TELEMETRY_VERSION", "1.0.0"),
            ("PROVIDE_TRACE_ENABLED", "true"),
            ("PROVIDE_METRICS_ENABLED", "true"),
        ],
        || {
            reset_runtime();
            setup_telemetry().expect("setup should succeed");

            std::env::set_var("PROVIDE_TELEMETRY_ENV", "prod");
            std::env::set_var("PROVIDE_TELEMETRY_VERSION", "2.0.0");
            std::env::set_var("PROVIDE_TRACE_ENABLED", "false");
            std::env::set_var("PROVIDE_METRICS_ENABLED", "false");

            let reloaded = reload_runtime_from_env().expect("reload should succeed");
            assert_eq!(reloaded.environment, "dev");
            assert_eq!(reloaded.version, "1.0.0");
            assert!(reloaded.tracing.enabled);
            assert!(reloaded.metrics.enabled);
        },
    );
}

#[test]
fn runtime_test_reconfigure_telemetry_none_reads_environment() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(
        &[
            ("PROVIDE_TELEMETRY_SERVICE_NAME", "from-env"),
            ("PROVIDE_TELEMETRY_ENV", "stage"),
        ],
        || {
            reset_runtime();
            #[cfg(not(feature = "otel"))]
            setup_telemetry().expect("setup should succeed");

            let cfg = reconfigure_telemetry(None).expect("reconfigure should read env");
            assert_eq!(cfg.service_name, "from-env");
            assert_eq!(cfg.environment, "stage");
        },
    );
}

#[cfg(feature = "otel")]
#[test]
fn runtime_test_reconfigure_telemetry_rejects_identity_change_when_otel_provider_is_live() {
    let _guard = runtime_lock().lock().expect("runtime lock poisoned");
    with_env(
        &[
            ("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318"),
            ("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf"),
        ],
        || {
            reset_runtime();
            let current = setup_telemetry().expect("setup should succeed");
            let status = get_runtime_status();
            assert!(status.providers.logs, "logs provider should be live");
            assert!(status.providers.traces, "traces provider should be live");
            assert!(status.providers.metrics, "metrics provider should be live");

            let mut hot_only = current.clone();
            hot_only.sampling.logs_rate = 0.75;
            let updated = reconfigure_telemetry(Some(hot_only))
                .expect("hot-only drift must remain allowed with live providers");
            assert_eq!(updated.sampling.logs_rate, 0.75);

            let mut changed = current.clone();
            changed.service_name = "other-service".to_string();

            let err = reconfigure_telemetry(Some(changed))
                .expect_err("provider-changing identity drift must be rejected");
            assert!(err.message.contains("restart the process"));

            let mut changed = current.clone();
            changed.logging.otlp_endpoint = Some("http://127.0.0.1:4319/v1/logs".to_string());
            let err = reconfigure_telemetry(Some(changed))
                .expect_err("live log provider drift must be rejected");
            assert!(err.message.contains("restart the process"));

            let mut changed = current.clone();
            changed.tracing.otlp_endpoint = Some("http://127.0.0.1:4319/v1/traces".to_string());
            let err = reconfigure_telemetry(Some(changed))
                .expect_err("live trace provider drift must be rejected");
            assert!(err.message.contains("restart the process"));

            let mut changed = current.clone();
            changed.metrics.metric_export_interval_ms += 1;
            let err = reconfigure_telemetry(Some(changed))
                .expect_err("live metrics provider drift must be rejected");
            assert!(err.message.contains("restart the process"));
        },
    );
}
