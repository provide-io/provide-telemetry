// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use crate::config::TelemetryConfig;
use crate::errors::TelemetryError;

#[cfg(feature = "otel")]
mod async_runtime;
#[cfg(feature = "otel")]
mod endpoint;
#[cfg(feature = "otel-grpc")]
mod grpc;
#[cfg(feature = "otel")]
pub(crate) mod logs;
#[cfg(feature = "otel")]
pub(crate) mod metrics;
#[cfg(feature = "otel")]
pub(crate) mod resilient;
#[cfg(feature = "otel")]
mod resource;
#[cfg(feature = "otel")]
pub(crate) mod traces;

#[cfg(feature = "otel")]
pub(crate) fn setup_otel(config: &TelemetryConfig) -> Result<(), TelemetryError> {
    // Build the resource once and clone for each provider (cheap — Resource
    // is internally Arc'd).
    let resource = resource::build_resource(config);
    traces::install_tracer_provider(config, resource.clone())?;
    metrics::install_meter_provider(config, resource.clone())?;
    logs::install_logger_provider(config, resource)?;
    Ok(())
}

#[cfg(feature = "otel")]
fn map_exporter_build<T, E: std::fmt::Display>(
    result: Result<T, E>,
    signal: &str,
) -> Result<T, TelemetryError> {
    result.map_err(|err| TelemetryError::new(format!("OTLP {signal} exporter build failed: {err}")))
}

#[cfg(not(feature = "otel"))]
pub(crate) fn setup_otel(_config: &TelemetryConfig) -> Result<(), TelemetryError> {
    Ok(())
}

pub(crate) fn shutdown_otel() {
    #[cfg(feature = "otel")]
    {
        logs::shutdown_logger_provider();
        metrics::shutdown_meter_provider();
        traces::shutdown_tracer_provider();
    }
}

pub(crate) fn otel_installed() -> bool {
    #[cfg(feature = "otel")]
    {
        traces::tracer_provider_installed()
            || metrics::meter_provider_installed()
            || logs::logger_provider_installed()
    }

    #[cfg(not(feature = "otel"))]
    {
        false
    }
}

pub fn otel_installed_for_tests() -> bool {
    otel_installed()
}

pub fn _reset_otel_for_tests() {
    shutdown_otel();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(not(feature = "otel"))]
    #[test]
    fn otel_test_installed_for_tests_is_false_without_feature() {
        assert!(!otel_installed_for_tests());
    }

    #[cfg(feature = "otel")]
    #[test]
    fn otel_test_installed_for_tests_matches_runtime_state_with_feature() {
        assert_eq!(otel_installed_for_tests(), otel_installed());
    }

    #[cfg(feature = "otel")]
    #[test]
    fn setup_otel_surfaces_tracer_exporter_errors() {
        let mut cfg = TelemetryConfig::default();
        cfg.tracing.otlp_endpoint = Some("ftp://collector:4317".to_string());
        cfg.exporter.traces_fail_open = false;

        let err = setup_otel(&cfg).expect_err("invalid tracing endpoint must fail setup");
        assert!(err.message.contains("scheme"));
    }

    #[cfg(feature = "otel")]
    #[test]
    fn setup_otel_surfaces_meter_exporter_errors_after_traces_short_circuit() {
        let mut cfg = TelemetryConfig::default();
        cfg.tracing.enabled = false;
        cfg.metrics.enabled = true;
        cfg.metrics.otlp_endpoint = Some("ftp://collector:4318".to_string());
        cfg.exporter.metrics_fail_open = false;

        let err = setup_otel(&cfg).expect_err("invalid metrics endpoint must fail setup");
        assert!(err.message.contains("scheme"));
    }

    #[cfg(feature = "otel")]
    #[test]
    fn setup_otel_surfaces_logger_exporter_errors_after_other_signals_short_circuit() {
        let mut cfg = TelemetryConfig::default();
        cfg.tracing.enabled = false;
        cfg.metrics.enabled = false;
        cfg.logging.otlp_endpoint = Some("ftp://collector:4318".to_string());
        cfg.exporter.logs_fail_open = false;

        let err = setup_otel(&cfg).expect_err("invalid logs endpoint must fail setup");
        assert!(err.message.contains("scheme"));
    }

    #[cfg(feature = "otel")]
    #[test]
    fn map_exporter_build_formats_signal_specific_errors() {
        let err = map_exporter_build::<(), _>(Err("boom"), "logs")
            .expect_err("fake exporter error should map");
        assert_eq!(err.message, "OTLP logs exporter build failed: boom");
    }
}
