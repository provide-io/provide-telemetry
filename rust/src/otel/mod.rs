// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use crate::config::TelemetryConfig;
use crate::errors::TelemetryError;

pub(crate) mod adopt;
#[cfg(feature = "otel")]
mod async_runtime;
#[cfg(feature = "otel")]
mod endpoint;
#[cfg(feature = "otel")]
mod flush;
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

/// Run `flush` under the bounded-shutdown deadline, on a detached worker when
/// one applies. `flush` reports whether the export succeeded.
///
/// Returns false when the deadline expired and the worker was abandoned, and
/// also when the drain finished but failed — both mean records may still be
/// sitting in the exporter's queue, which is what the caller needs to know.
#[cfg(feature = "otel")]
fn bounded_flush<F>(signal: &str, flush: F) -> bool
where
    F: FnOnce() -> bool + Send + 'static,
{
    let timeout_secs = crate::runtime::get_runtime_config()
        .map(|cfg| cfg.exporter.logs_shutdown_timeout_seconds)
        .unwrap_or(5.0);

    if timeout_secs <= 0.0 {
        // Caller opted out of bounding — do the synchronous drain.
        return flush();
    }

    let timeout = std::time::Duration::from_secs_f64(timeout_secs);
    let (tx, rx) = std::sync::mpsc::channel();
    let _worker = std::thread::Builder::new()
        .name(format!("provide-{signal}-flush"))
        .spawn(move || {
            let _ = tx.send(flush());
        })
        .expect("OS must allow spawning a flush worker thread");

    match rx.recv_timeout(timeout) {
        Ok(true) => true,
        // The drain finished in time but the exporter rejected it: reporting Ok
        // here would tell a caller its records are out when they are not.
        Ok(false) => {
            eprintln!("provide_telemetry: {signal} flush failed");
            false
        }
        Err(_) => {
            eprintln!(
                "provide_telemetry: {signal} flush exceeded {:.3}s deadline; abandoning background flush",
                timeout.as_secs_f64(),
            );
            false
        }
    }
}

/// Force-flush every installed provider, leaving them installed.
///
/// Returns false when any signal was abandoned at the deadline. Every signal
/// gets its attempt regardless — one stalled exporter must not deny the others
/// their drain.
pub(crate) fn flush_otel() -> bool {
    #[cfg(feature = "otel")]
    {
        let logs = flush::flush_logger_provider();
        let traces = flush::flush_tracer_provider();
        let metrics = flush::flush_meter_provider();
        logs && traces && metrics
    }

    #[cfg(not(feature = "otel"))]
    {
        true
    }
}

/// True when facade spans should route through the global tracer provider:
/// either we installed one, or the host asserted that it did.
///
/// Gated on the signal not having been switched off by a loaded config, because
/// that is what the emit path checks first. Reporting or using a provider for a
/// disabled signal would claim an export path nothing is meant to reach, and
/// would put Rust out of step with the other three facades.
#[cfg(feature = "otel")]
pub(crate) fn traces_provider_effective() -> bool {
    crate::runtime::tracing_enabled_by_loaded_config()
        && (traces::tracer_provider_installed() || adopt::traces_adopted())
}

/// Metrics counterpart of [`traces_provider_effective`].
#[cfg(feature = "otel")]
pub(crate) fn metrics_provider_effective() -> bool {
    crate::runtime::metrics_enabled_by_loaded_config()
        && (metrics::meter_provider_installed() || adopt::metrics_adopted())
}

pub(crate) fn shutdown_otel() {
    // Adopted providers belong to the host: drop the assertion, shut nothing down.
    adopt::release_adopted_providers();
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
        let _guard = crate::testing::acquire_test_state_lock();
        crate::testing::reset_telemetry_state();

        let mut cfg = TelemetryConfig::default();
        cfg.tracing.otlp_endpoint = Some("ftp://collector:4317".to_string());
        cfg.exporter.traces_fail_open = false;

        let err = setup_otel(&cfg).expect_err("invalid tracing endpoint must fail setup");
        assert!(err.message.contains("scheme"));

        crate::testing::reset_telemetry_state();
    }

    #[cfg(feature = "otel")]
    #[test]
    fn setup_otel_surfaces_meter_exporter_errors_after_traces_short_circuit() {
        let _guard = crate::testing::acquire_test_state_lock();
        crate::testing::reset_telemetry_state();

        let mut cfg = TelemetryConfig::default();
        cfg.tracing.enabled = false;
        cfg.metrics.enabled = true;
        cfg.metrics.otlp_endpoint = Some("ftp://collector:4318".to_string());
        cfg.exporter.metrics_fail_open = false;

        let err = setup_otel(&cfg).expect_err("invalid metrics endpoint must fail setup");
        assert!(err.message.contains("scheme"));

        crate::testing::reset_telemetry_state();
    }

    #[cfg(feature = "otel")]
    #[test]
    fn setup_otel_surfaces_logger_exporter_errors_after_other_signals_short_circuit() {
        let _guard = crate::testing::acquire_test_state_lock();
        crate::testing::reset_telemetry_state();

        let mut cfg = TelemetryConfig::default();
        cfg.tracing.enabled = false;
        cfg.metrics.enabled = false;
        cfg.logging.otlp_endpoint = Some("ftp://collector:4318".to_string());
        cfg.exporter.logs_fail_open = false;

        let err = setup_otel(&cfg).expect_err("invalid logs endpoint must fail setup");
        assert!(err.message.contains("scheme"));

        crate::testing::reset_telemetry_state();
    }

    #[cfg(feature = "otel")]
    #[test]
    fn map_exporter_build_formats_signal_specific_errors() {
        let err = map_exporter_build::<(), _>(Err("boom"), "logs")
            .expect_err("fake exporter error should map");
        assert_eq!(err.message, "OTLP logs exporter build failed: boom");
    }

    // Kills: `||` -> `&&` in otel_installed. With AND, installing only one of the
    // three providers makes otel_installed() return false; with OR (the original)
    // any one provider is sufficient.
    #[cfg(feature = "otel")]
    #[tokio::test(flavor = "multi_thread", worker_threads = 1)]
    async fn otel_installed_returns_true_when_only_tracer_provider_is_installed() {
        let _guard = crate::testing::acquire_test_state_lock();
        crate::testing::reset_telemetry_state();

        let mut cfg = TelemetryConfig::default();
        cfg.tracing.otlp_endpoint = Some("http://127.0.0.1:1/never".to_string());
        cfg.exporter.traces_fail_open = true;
        let resource = resource::build_resource(&cfg);
        traces::install_tracer_provider(&cfg, resource)
            .expect("tracer provider should install under fail_open");

        assert!(traces::tracer_provider_installed());
        assert!(!metrics::meter_provider_installed());
        assert!(!logs::logger_provider_installed());
        assert!(otel_installed());

        crate::testing::reset_telemetry_state();
    }
}

#[cfg(all(test, feature = "otel"))]
mod bounded_flush_tests {
    use super::*;

    /// A drain that finished in time but failed must not report success — the
    /// caller is deciding whether its records are safely out.
    #[test]
    fn a_failed_drain_is_reported_as_failure() {
        assert!(!bounded_flush("traces", || false));
    }

    #[test]
    fn a_successful_drain_is_reported_as_success() {
        assert!(bounded_flush("traces", || true));
    }

    /// A drain still running at the deadline is abandoned and reported as a
    /// failure — the records are still in the exporter's queue, which is exactly
    /// what the caller is asking about. This is the path that separates flush
    /// from shutdown: shutdown suppresses its library-applied deadline, flush
    /// must not.
    #[test]
    fn a_drain_abandoned_at_the_deadline_is_reported_as_failure() {
        use crate::config::TelemetryConfig;
        use crate::testing::acquire_test_state_lock;

        let _guard = acquire_test_state_lock();
        let mut cfg = TelemetryConfig::default();
        cfg.exporter.logs_shutdown_timeout_seconds = 0.05;
        crate::runtime::set_active_config(Some(cfg));

        let released = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
        let worker_released = std::sync::Arc::clone(&released);
        assert!(!bounded_flush("metrics", move || {
            // Outlive the deadline, then exit so the thread is not left running
            // for the rest of the suite.
            while !worker_released.load(std::sync::atomic::Ordering::Acquire) {
                std::thread::sleep(std::time::Duration::from_millis(5));
            }
            true
        }));
        released.store(true, std::sync::atomic::Ordering::Release);

        crate::runtime::set_active_config(None);
    }

    /// With bounding switched off the drain runs inline; its result still counts.
    #[test]
    fn unbounded_drain_still_reports_its_result() {
        use crate::config::TelemetryConfig;
        use crate::testing::acquire_test_state_lock;

        let _guard = acquire_test_state_lock();
        let mut cfg = TelemetryConfig::default();
        cfg.exporter.logs_shutdown_timeout_seconds = 0.0;
        crate::runtime::set_active_config(Some(cfg));

        assert!(!bounded_flush("logs", || false));
        assert!(bounded_flush("logs", || true));

        crate::runtime::set_active_config(None);
    }
}
