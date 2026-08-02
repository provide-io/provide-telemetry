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

/// The configured bounded-shutdown deadline, for callers that passed none.
#[cfg(feature = "otel")]
fn configured_drain_seconds() -> f64 {
    crate::runtime::get_runtime_config()
        .map(|cfg| cfg.exporter.logs_shutdown_timeout_seconds)
        .unwrap_or(5.0)
}

/// Run `teardown` under the caller's deadline, on a detached worker when one
/// applies.
///
/// Bounded for the same reason [`bounded_flush`] is: `SdkTracerProvider::shutdown`
/// and its logger/meter counterparts take no timeout parameter and join their
/// batch worker with the SDK's own 30s default. Without this the deadline a
/// SIGTERM handler passed buys nothing — the pre-drain returns on time and the
/// teardown right behind it blocks until the collector answers or the pod is
/// SIGKILLed.
///
/// On expiry the worker is abandoned. The provider slot has already been taken
/// by the caller, so the abandoned thread is draining a provider nothing can
/// reach any more.
#[cfg(feature = "otel")]
pub(super) fn bounded_teardown<F>(signal: &str, timeout_seconds: Option<f64>, teardown: F)
where
    F: FnOnce() + Send + 'static,
{
    let timeout_secs = timeout_seconds.unwrap_or_else(configured_drain_seconds);

    // No usable bound (<= 0, NaN, or infinity) — do the synchronous teardown.
    // See `drain_deadline` for why NaN and infinity cannot be handed to
    // `Duration::from_secs_f64`.
    let Some(timeout) = drain_deadline(timeout_secs) else {
        teardown();
        return;
    };
    let (tx, rx) = std::sync::mpsc::channel();
    let _worker = std::thread::Builder::new()
        .name(format!("provide-{signal}-shutdown"))
        .spawn(move || {
            teardown();
            let _ = tx.send(());
        })
        .expect("OS must allow spawning a shutdown worker thread");

    if rx.recv_timeout(timeout).is_err() {
        eprintln!(
            "provide_telemetry: {signal} shutdown exceeded {:.3}s deadline; abandoning background flush",
            timeout.as_secs_f64(),
        );
    }
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
    let timeout_secs = timeout_seconds.unwrap_or_else(configured_drain_seconds);

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
        // Drain the three together. Evaluated one field at a time they each take
        // the caller's whole deadline in turn, so three stalled exporters spend
        // three times the budget a SIGTERM handler passed — the overrun the
        // deadline exists to prevent. Each drain is itself bounded, so the joins
        // here are bounded too.
        std::thread::scope(|scope| {
            let logs = scope.spawn(|| flush::flush_logger_provider(timeout_seconds));
            let traces = scope.spawn(|| flush::flush_tracer_provider(timeout_seconds));
            let metrics = flush::flush_meter_provider(timeout_seconds);
            SignalDrains {
                logs: logs.join().expect("logs drain worker must not panic"),
                traces: traces.join().expect("traces drain worker must not panic"),
                metrics,
            }
        })
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

/// Tear down every provider we installed, bounded by the caller's deadline.
///
/// `timeout_seconds` bounds each signal's flush-and-shutdown; `None` uses the
/// configured one. The three run concurrently for the same reason
/// [`flush_otel_by_signal`] does: in sequence they each take the whole deadline,
/// so a caller's termination grace period would cover only a third of the work.
pub(crate) fn shutdown_otel(timeout_seconds: Option<f64>) {
    // Adopted providers belong to the host: drop the assertion, shut nothing down.
    adopt::release_adopted_providers();
    #[cfg(feature = "otel")]
    {
        std::thread::scope(|scope| {
            scope.spawn(|| logs::shutdown_logger_provider(timeout_seconds));
            scope.spawn(|| metrics::shutdown_meter_provider(timeout_seconds));
            traces::shutdown_tracer_provider(timeout_seconds);
        });
    }

    #[cfg(not(feature = "otel"))]
    {
        let _ = timeout_seconds;
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
    shutdown_otel(None);
}

#[cfg(test)]
#[path = "mod_tests.rs"]
mod mod_tests;

#[cfg(all(test, feature = "otel"))]
#[path = "bounded_flush_tests.rs"]
mod bounded_flush_tests;
