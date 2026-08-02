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

/// Ceiling applied to a drain deadline. Past this a "bounded" drain is not
/// bounding anything, and it keeps the value well inside what
/// `Duration::from_secs_f64` can represent.
#[cfg(feature = "otel")]
const MAX_DRAIN_SECONDS: f64 = 86_400.0;

/// Turn a drain deadline in seconds into a `Duration`, or `None` when the value
/// asks for no bound at all.
///
/// `Duration::from_secs_f64` panics on NaN, on ±inf, and on anything past
/// `u64::MAX` seconds. These deadlines arrive from a public API argument
/// (`flush_telemetry`/`shutdown_telemetry`) and from config, and the callers
/// are shutdown paths — a panic there aborts the process mid-termination and
/// loses every queued record, which is the opposite of what a caller passing a
/// deadline is asking for.
///
/// The guard is written as "finite and positive" rather than as a negated
/// comparison so NaN lands in the unbounded branch alongside `<= 0` ("caller
/// opted out") and infinity ("drain without a deadline"): every comparison
/// against NaN is false, so `x <= 0.0` alone would let it through. A finite
/// value is clamped so the conversion cannot overflow.
#[cfg(feature = "otel")]
pub(super) fn drain_deadline(timeout_secs: f64) -> Option<std::time::Duration> {
    if !timeout_secs.is_finite() || timeout_secs <= 0.0 {
        return None;
    }
    Some(std::time::Duration::from_secs_f64(
        timeout_secs.min(MAX_DRAIN_SECONDS),
    ))
}

/// Run `flush` under the bounded-shutdown deadline, on a detached worker when
/// one applies. `flush` reports whether the export succeeded.
///
/// Returns false when the deadline expired and the worker was abandoned, and
/// also when the drain finished but failed — both mean records may still be
/// sitting in the exporter's queue, which is what the caller needs to know.
#[cfg(feature = "otel")]
fn bounded_flush<F>(signal: &str, timeout_seconds: Option<f64>, flush: F) -> bool
where
    F: FnOnce() -> bool + Send + 'static,
{
    // A caller-supplied deadline wins over the configured one, so a caller with
    // a budget (a SIGTERM handler, a request boundary) can bound this call.
    let timeout_secs = timeout_seconds.unwrap_or_else(|| {
        crate::runtime::get_runtime_config()
            .map(|cfg| cfg.exporter.logs_shutdown_timeout_seconds)
            .unwrap_or(5.0)
    });

    // No usable bound (<= 0, NaN, or infinity) — do the synchronous drain.
    let Some(timeout) = drain_deadline(timeout_secs) else {
        return flush();
    };
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
pub(crate) fn flush_otel(timeout_seconds: Option<f64>) -> bool {
    let per_signal = flush_otel_by_signal(timeout_seconds);
    per_signal.logs && per_signal.traces && per_signal.metrics
}

/// One drain outcome per signal.
///
/// The signals drain against three potentially different endpoints, so an
/// unreachable logs collector says nothing about traces and metrics. Collapsing
/// them to a single bool — which [`flush_otel`] still does for its own callers —
/// makes a facade report every signal as failed when one was.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct SignalDrains {
    pub logs: bool,
    pub traces: bool,
    pub metrics: bool,
}

pub(crate) fn flush_otel_by_signal(timeout_seconds: Option<f64>) -> SignalDrains {
    #[cfg(feature = "otel")]
    {
        SignalDrains {
            logs: flush::flush_logger_provider(timeout_seconds),
            traces: flush::flush_tracer_provider(timeout_seconds),
            metrics: flush::flush_meter_provider(timeout_seconds),
        }
    }

    #[cfg(not(feature = "otel"))]
    {
        let _ = timeout_seconds;
        SignalDrains {
            logs: true,
            traces: true,
            metrics: true,
        }
    }
}

/// Which signals have a provider *we* installed — the ones a drain can reach.
///
/// A provider adopted from the OTel globals belongs to the host: `shutdown_otel`
/// releases the assertion without shutting it down, and the flush helpers never
/// see it. Reporting such a signal as flushed would tell a caller its records
/// are out when they are still in the host's batch processor.
pub(crate) fn owned_signals() -> SignalDrains {
    #[cfg(feature = "otel")]
    {
        SignalDrains {
            logs: logs::logger_provider_installed(),
            traces: traces::tracer_provider_installed(),
            metrics: metrics::meter_provider_installed(),
        }
    }

    #[cfg(not(feature = "otel"))]
    {
        SignalDrains {
            logs: false,
            traces: false,
            metrics: false,
        }
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

    /// `Duration::from_secs_f64` panics on NaN, on ±inf, and past u64::MAX
    /// seconds. `drain_deadline` must absorb all of those rather than let a
    /// caller-supplied `timeout_seconds` abort the process from a shutdown path.
    #[cfg(feature = "otel")]
    #[test]
    fn otel_test_drain_deadline_rejects_unusable_values() {
        assert_eq!(drain_deadline(f64::NAN), None);
        assert_eq!(drain_deadline(f64::INFINITY), None);
        assert_eq!(drain_deadline(f64::NEG_INFINITY), None);
        assert_eq!(drain_deadline(0.0), None);
        assert_eq!(drain_deadline(-1.5), None);
    }

    #[cfg(feature = "otel")]
    #[test]
    fn otel_test_drain_deadline_passes_through_and_clamps() {
        assert_eq!(
            drain_deadline(2.5),
            Some(std::time::Duration::from_secs_f64(2.5))
        );
        // f64::MAX seconds is well past what Duration can hold; clamping is what
        // keeps the conversion from panicking.
        assert_eq!(
            drain_deadline(f64::MAX),
            Some(std::time::Duration::from_secs_f64(MAX_DRAIN_SECONDS))
        );
        assert_eq!(
            drain_deadline(MAX_DRAIN_SECONDS - 1.0),
            Some(std::time::Duration::from_secs_f64(MAX_DRAIN_SECONDS - 1.0))
        );
    }

    /// The whole point of the guard: these arguments used to panic inside
    /// `shutdown_telemetry`, aborting the process instead of draining.
    #[cfg(feature = "otel")]
    #[test]
    fn otel_test_bounded_flush_survives_a_non_finite_caller_timeout() {
        assert!(bounded_flush("logs", Some(f64::NAN), || true));
        assert!(bounded_flush("traces", Some(f64::INFINITY), || true));
        assert!(!bounded_flush("metrics", Some(f64::MAX), || false));
    }

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

    #[cfg(feature = "otel")]
    #[tokio::test(flavor = "multi_thread", worker_threads = 1)]
    async fn otel_installed_returns_true_when_only_logger_provider_is_installed() {
        let _guard = crate::testing::acquire_test_state_lock();
        crate::testing::reset_telemetry_state();

        let mut cfg = TelemetryConfig::default();
        cfg.tracing.enabled = false;
        cfg.metrics.enabled = false;
        cfg.logging.otlp_endpoint = Some("http://127.0.0.1:1/never".to_string());
        cfg.exporter.logs_fail_open = true;
        let resource = resource::build_resource(&cfg);
        logs::install_logger_provider(&cfg, resource)
            .expect("logger provider should install under fail_open");

        assert!(!traces::tracer_provider_installed());
        assert!(!metrics::meter_provider_installed());
        assert!(logs::logger_provider_installed());
        assert!(otel_installed());

        _reset_otel_for_tests();
        assert!(!traces::tracer_provider_installed());
        assert!(!metrics::meter_provider_installed());
        assert!(!logs::logger_provider_installed());
        assert!(!otel_installed());

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
        assert!(!bounded_flush("traces", None, || false));
    }

    #[test]
    fn a_successful_drain_is_reported_as_success() {
        assert!(bounded_flush("traces", None, || true));
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

        let (release_tx, release_rx) = std::sync::mpsc::channel();
        assert!(!bounded_flush("metrics", None, move || {
            // Outlive the library deadline, but keep a finite independent bound:
            // a comparison mutant must fail this assertion promptly rather than
            // strand the test inside a synchronous drain.
            let _ = release_rx.recv_timeout(std::time::Duration::from_millis(250));
            true
        }));
        let _ = release_tx.send(());

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

        assert!(!bounded_flush("logs", None, || false));
        assert!(bounded_flush("logs", None, || true));

        crate::runtime::set_active_config(None);
    }
}
