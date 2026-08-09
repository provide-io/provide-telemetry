// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use crate::config::TelemetryConfig;
use crate::errors::TelemetryError;
use crate::sampling::Signal;

pub(crate) mod adopt;
#[cfg(feature = "otel")]
mod async_runtime;
#[cfg(feature = "otel")]
mod bounded;
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

// The bounded drain/teardown primitives live in `bounded.rs`; the flush and
// shutdown paths below and the per-signal modules reach them through these
// re-exports.
#[cfg(feature = "otel")]
pub(crate) use bounded::_reset_abandoned_workers_for_tests;
#[cfg(all(test, feature = "otel"))]
pub(crate) use bounded::drain_deadline;
#[cfg(feature = "otel")]
pub(crate) use bounded::{bounded_flush, bounded_teardown};

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

/// Count, per signal we own, a drain that is about to park the calling thread
/// while that thread belongs to an async runtime.
///
/// The Rust reading of `async_blocking_risk_*`. `flush_telemetry` and
/// `shutdown_telemetry` are synchronous by signature, so an async application
/// calls them from inside an `async fn` and the whole drain runs on a Tokio
/// worker: the scoped drain threads below are spawned *and joined* here, so
/// every other task that worker was driving stops until the slowest signal
/// returns or its deadline expires. That is the same hazard Python counts for a
/// blocking export on an asyncio loop and .NET counts for a thread carrying a
/// `SynchronizationContext`, and `Handle::try_current` is how Tokio lets us ask.
///
/// It has to be asked *here*, on the caller's thread and before the drain
/// starts: inside the drain workers the answer is always "no runtime", which is
/// exactly why the drain primitives themselves cannot see this.
///
/// Only signals with a provider of ours are counted — [`owned_signals`]. A
/// signal we never drain cannot have stalled anything, so counting it would
/// make the metric unusable for finding which exporter is the slow one.
fn note_blocking_drain() {
    if tokio::runtime::Handle::try_current().is_err() {
        return;
    }
    let owned = owned_signals();
    if owned.logs {
        crate::health::increment_async_blocking_risk(Signal::Logs);
    }
    if owned.traces {
        crate::health::increment_async_blocking_risk(Signal::Traces);
    }
    if owned.metrics {
        crate::health::increment_async_blocking_risk(Signal::Metrics);
    }
}

pub(crate) fn flush_otel_by_signal(timeout_seconds: Option<f64>) -> SignalDrains {
    note_blocking_drain();

    #[cfg(feature = "otel")]
    {
        // Drain the three together. Evaluated one field at a time they each take
        // the caller's whole deadline in turn, so three stalled exporters spend
        // three times the budget a SIGTERM handler passed — the overrun the
        // deadline exists to prevent. Each drain is itself bounded, so the joins
        // here are bounded too. A spawn refused by the OS (thread limit) falls
        // back to draining that signal inline instead of panicking mid-shutdown.
        // Each drain closure is spawned and, on a failed spawn, reused as the
        // inline fallback — one body, so both paths drain identically.
        let drain_logs = || flush::flush_logger_provider(timeout_seconds);
        let drain_traces = || flush::flush_tracer_provider(timeout_seconds);
        std::thread::scope(|scope| {
            let logs = std::thread::Builder::new()
                .name("provide-logs-drain".to_string())
                .spawn_scoped(scope, drain_logs);
            let traces = std::thread::Builder::new()
                .name("provide-traces-drain".to_string())
                .spawn_scoped(scope, drain_traces);
            let metrics = flush::flush_meter_provider(timeout_seconds);
            SignalDrains {
                logs: bounded::join_or_inline(logs, drain_logs),
                traces: bounded::join_or_inline(traces, drain_traces),
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
    // Before anything is torn down: owned_signals() must still see the providers
    // this teardown is about to take out of their slots.
    note_blocking_drain();
    // Adopted providers belong to the host: drop the assertion, shut nothing down.
    adopt::release_adopted_providers();
    #[cfg(feature = "otel")]
    {
        // A spawn refused by the OS (thread limit) falls back to tearing that
        // signal down inline instead of panicking mid-shutdown — degraded to
        // sequential, but every signal still drains. Each teardown closure is
        // spawned and, on a failed spawn, reused as the inline fallback.
        let teardown_logs = || logs::shutdown_logger_provider(timeout_seconds);
        let teardown_metrics = || metrics::shutdown_meter_provider(timeout_seconds);
        std::thread::scope(|scope| {
            let logs = std::thread::Builder::new()
                .name("provide-logs-teardown".to_string())
                .spawn_scoped(scope, teardown_logs);
            let metrics = std::thread::Builder::new()
                .name("provide-metrics-teardown".to_string())
                .spawn_scoped(scope, teardown_metrics);
            traces::shutdown_tracer_provider(timeout_seconds);
            bounded::join_or_inline(logs, teardown_logs);
            bounded::join_or_inline(metrics, teardown_metrics);
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

#[cfg(all(test, feature = "otel"))]
#[path = "async_blocking_risk_tests.rs"]
mod async_blocking_risk_tests;
