// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use serde::{Deserialize, Serialize};

use crate::config::{RuntimeOverrides, TelemetryConfig};
use crate::errors::TelemetryError;
use crate::otel::DrainOutcome;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SignalStatus {
    pub logs: bool,
    pub traces: bool,
    pub metrics: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum ProviderMode {
    Owned,
    Host,
    Local,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum RuntimeState {
    Local,
    Starting,
    Ready,
    Degraded,
    Reconfiguring,
    Stopping,
    Stopped,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct SignalFlushResult {
    pub flushed: bool,
    pub not_installed: bool,
    pub not_owned: bool,
    pub timed_out: bool,
    pub failed: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct FlushResult {
    pub logs: SignalFlushResult,
    pub traces: SignalFlushResult,
    pub metrics: SignalFlushResult,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ReconfigureResult {
    pub applied: bool,
    pub previous: Option<TelemetryConfig>,
    pub current: Option<TelemetryConfig>,
    pub error: Option<String>,
    pub state: RuntimeState,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuntimeStatus {
    pub setup_done: bool,
    pub signals: SignalStatus,
    pub providers: SignalStatus,
    pub fallback: SignalStatus,
    pub setup_error: Option<String>,
}

#[allow(non_camel_case_types)]
pub type provider_mode = ProviderMode;
#[allow(non_camel_case_types)]
pub type runtime_state = RuntimeState;
#[allow(non_camel_case_types)]
pub type signal_flush_result = SignalFlushResult;
#[allow(non_camel_case_types)]
pub type flush_result = FlushResult;
#[allow(non_camel_case_types)]
pub type reconfigure_result = ReconfigureResult;
#[allow(non_camel_case_types)]
pub type telemetry_config = TelemetryConfig;
#[allow(non_camel_case_types)]
pub type telemetry_runtime = TelemetryRuntime;
#[allow(non_camel_case_types)]
pub type runtime_status = RuntimeStatus;

/// True when any owned signal's drain was abandoned at its deadline.
///
/// `not_installed` and `not_owned` signals have nothing of ours to lose and
/// are not failures.
fn any_owned_drain_abandoned(result: &FlushResult) -> bool {
    result.logs.timed_out || result.traces.timed_out || result.metrics.timed_out
}

/// True when any owned signal's drain completed but was rejected by its
/// exporter — the `failed` half of the abandoned/failed split.
fn any_owned_drain_rejected(result: &FlushResult) -> bool {
    result.logs.failed || result.traces.failed || result.metrics.failed
}

/// One signal's flush outcome, from what is installed, what we own, and what
/// its drain reported.
///
/// A free function rather than a closure inside `flush` so it is reachable
/// without a live provider: in a build with no OTel providers installed, only
/// the `not_installed` arm of the inline version ever ran, leaving the rest
/// untested. Mirrors Python's `_signal_flush_result`.
///
/// A signal with no provider has nothing to drain. A signal whose provider was
/// adopted from the OTel globals belongs to the host — we leave it alone, so
/// calling it `flushed` would claim records are out while they sit in the
/// host's batch processor. An owned drain carries the three-way outcome
/// through: `flushed`, `failed` (the exporter rejected the drain inside the
/// deadline) or `timed_out` (abandoned at the deadline) — the same split
/// Python, Go and TypeScript populate.
fn signal_flush_result(installed: bool, owned: bool, outcome: DrainOutcome) -> SignalFlushResult {
    if !installed {
        return SignalFlushResult {
            not_installed: true,
            ..SignalFlushResult::default()
        };
    }
    if !owned {
        return SignalFlushResult {
            not_owned: true,
            ..SignalFlushResult::default()
        };
    }
    SignalFlushResult {
        flushed: outcome == DrainOutcome::Drained,
        timed_out: outcome == DrainOutcome::TimedOut,
        failed: outcome == DrainOutcome::Failed,
        ..SignalFlushResult::default()
    }
}

pub struct TelemetryRuntime {
    provider_mode: ProviderMode,
    state: RuntimeState,
}

impl Default for TelemetryRuntime {
    fn default() -> Self {
        Self::new()
    }
}

impl TelemetryRuntime {
    pub fn new() -> Self {
        Self {
            provider_mode: ProviderMode::Owned,
            state: RuntimeState::Ready,
        }
    }

    /// Start the runtime, optionally with an explicit config.
    ///
    /// `None` reads the environment. Mirrors Python's `start(config)`,
    /// TypeScript's `start(config?)` and Go's `Start(ctx, opts...)`.
    pub fn start(
        &mut self,
        config: Option<TelemetryConfig>,
    ) -> Result<TelemetryConfig, TelemetryError> {
        self.state = RuntimeState::Starting;
        match crate::setup::setup_telemetry(config) {
            Ok(cfg) => {
                self.state = RuntimeState::Ready;
                Ok(cfg)
            }
            Err(err) => {
                self.state = RuntimeState::Degraded;
                Err(err)
            }
        }
    }

    /// Shut down, bounding the pre-teardown drain by `timeout_seconds`.
    pub fn shutdown(&mut self, timeout_seconds: Option<f64>) -> Result<(), TelemetryError> {
        self.state = RuntimeState::Stopping;
        let result = crate::setup::shutdown_telemetry(timeout_seconds);
        self.state = RuntimeState::Stopped;
        result
    }

    /// Flush installed providers, bounding the drain by `timeout_seconds`.
    ///
    /// Each signal reports its own outcome. A signal with no provider is
    /// `not_installed`; one whose provider was adopted from the OTel globals is
    /// `not_owned` (the host's to drain, so we leave it alone); the rest carry
    /// the result of their own drain, not an aggregate of all three.
    ///
    /// Returns `Err` when any owned signal's records may still be queued —
    /// abandoned at the deadline, or rejected by its exporter inside it — so
    /// `rt.flush(None)?` before a freeze fails loudly instead of freezing with
    /// records still queued — the contract `setup::flush_telemetry` has always
    /// had. The two error messages stay distinct: an exporter that rejected
    /// the drain in milliseconds never exceeded any deadline. Inspect the
    /// `FlushResult` on `Ok` for per-signal detail.
    pub fn flush(&self, timeout_seconds: Option<f64>) -> Result<FlushResult, TelemetryError> {
        let providers = crate::runtime::get_runtime_status().providers;
        let owned = crate::otel::owned_signals();
        let drained = crate::otel::flush_otel_by_signal(timeout_seconds);
        let result = FlushResult {
            logs: signal_flush_result(providers.logs, owned.logs, drained.logs),
            traces: signal_flush_result(providers.traces, owned.traces, drained.traces),
            metrics: signal_flush_result(providers.metrics, owned.metrics, drained.metrics),
        };
        if any_owned_drain_abandoned(&result) {
            return Err(TelemetryError::new(
                "telemetry flush exceeded its deadline; records may not have been exported",
            ));
        }
        if any_owned_drain_rejected(&result) {
            return Err(TelemetryError::new(
                "telemetry flush failed: an exporter rejected the drain; records may not have been exported",
            ));
        }
        Ok(result)
    }

    pub fn get_logger(&self, name: Option<&str>) -> crate::logger::Logger {
        crate::logger::get_logger(name)
    }

    pub fn get_tracer(&self, name: Option<&str>) -> crate::tracer::Tracer {
        crate::tracing::get_tracer(name)
    }

    pub fn get_meter(&self, name: Option<&str>) -> crate::metrics::Meter {
        crate::metrics::get_meter(name)
    }

    pub fn get_runtime_config(&self) -> Option<TelemetryConfig> {
        crate::runtime::get_runtime_config()
    }

    pub fn get_runtime_status(&self) -> RuntimeStatus {
        crate::runtime::get_runtime_status()
    }

    pub fn update_config(&mut self, overrides: RuntimeOverrides) -> ReconfigureResult {
        let previous = crate::runtime::get_runtime_config();
        let next = match crate::runtime::update_runtime_config(overrides) {
            Ok(cfg) => Some(cfg),
            Err(err) => {
                return ReconfigureResult {
                    applied: false,
                    previous,
                    current: None,
                    error: Some(err.message),
                    state: self.state,
                };
            }
        };
        ReconfigureResult {
            applied: true,
            previous,
            current: next,
            error: None,
            state: self.state,
        }
    }

    pub fn reconfigure(
        &mut self,
        config: Option<TelemetryConfig>,
    ) -> Result<TelemetryConfig, TelemetryError> {
        crate::runtime::reconfigure_telemetry(config)
    }

    pub fn provider_mode(&self) -> ProviderMode {
        self.provider_mode
    }

    pub fn state(&self) -> RuntimeState {
        self.state
    }
}

#[cfg(test)]
mod signal_flush_result_tests {
    use super::{
        any_owned_drain_abandoned, any_owned_drain_rejected, signal_flush_result, DrainOutcome,
        FlushResult, SignalFlushResult,
    };

    fn drained() -> SignalFlushResult {
        SignalFlushResult {
            flushed: true,
            ..SignalFlushResult::default()
        }
    }

    fn abandoned() -> SignalFlushResult {
        SignalFlushResult {
            timed_out: true,
            ..SignalFlushResult::default()
        }
    }

    /// Each signal alone must trip the abandoned check — `rt.flush(None)?` is
    /// how a serverless handler learns its records are still queued, and an
    /// `&&` here would let a single stalled exporter pass silently.
    #[test]
    fn one_abandoned_signal_is_enough_to_report_an_abandoned_drain() {
        let clean = FlushResult {
            logs: drained(),
            traces: drained(),
            metrics: drained(),
        };
        assert!(!any_owned_drain_abandoned(&clean));

        for signal in ["logs", "traces", "metrics"] {
            let mut result = clean.clone();
            match signal {
                "logs" => result.logs = abandoned(),
                "traces" => result.traces = abandoned(),
                _ => result.metrics = abandoned(),
            }
            assert!(
                any_owned_drain_abandoned(&result),
                "an abandoned {signal} drain must be reported"
            );
        }
    }

    /// Signals that are not ours to drain are not failures: a host-owned
    /// provider or an absent one must not turn flush into an error.
    #[test]
    fn not_installed_and_not_owned_signals_are_not_abandoned_drains() {
        let result = FlushResult {
            logs: SignalFlushResult {
                not_installed: true,
                ..SignalFlushResult::default()
            },
            traces: SignalFlushResult {
                not_owned: true,
                ..SignalFlushResult::default()
            },
            metrics: drained(),
        };
        assert!(!any_owned_drain_abandoned(&result));
    }

    /// The full truth table. Each row is a distinct answer a caller acts on:
    /// nothing to drain, not ours to drain, drained, rejected by the exporter,
    /// or missed the deadline.
    #[test]
    fn covers_every_combination() {
        let cases: [(bool, bool, DrainOutcome, SignalFlushResult); 6] = [
            (
                false,
                false,
                DrainOutcome::Drained,
                SignalFlushResult {
                    not_installed: true,
                    ..SignalFlushResult::default()
                },
            ),
            (
                false,
                true,
                DrainOutcome::Drained,
                SignalFlushResult {
                    not_installed: true,
                    ..SignalFlushResult::default()
                },
            ),
            (
                true,
                false,
                DrainOutcome::Drained,
                SignalFlushResult {
                    not_owned: true,
                    ..SignalFlushResult::default()
                },
            ),
            (
                true,
                true,
                DrainOutcome::Drained,
                SignalFlushResult {
                    flushed: true,
                    ..SignalFlushResult::default()
                },
            ),
            (
                true,
                true,
                DrainOutcome::Failed,
                SignalFlushResult {
                    failed: true,
                    ..SignalFlushResult::default()
                },
            ),
            (
                true,
                true,
                DrainOutcome::TimedOut,
                SignalFlushResult {
                    timed_out: true,
                    ..SignalFlushResult::default()
                },
            ),
        ];

        for (installed, owned, outcome, want) in cases {
            let got = signal_flush_result(installed, owned, outcome);
            assert_eq!(
                got, want,
                "installed={installed} owned={owned} outcome={outcome:?}"
            );
        }
    }

    /// not_installed wins over not_owned: a signal with no provider at all is
    /// not "the host's to drain", it is simply absent.
    #[test]
    fn not_installed_takes_precedence_over_not_owned() {
        let got = signal_flush_result(false, false, DrainOutcome::TimedOut);
        assert!(got.not_installed);
        assert!(!got.not_owned);
        assert!(!got.flushed);
        assert!(!got.timed_out);
    }

    /// An owned, installed signal that missed its deadline is timed_out, never
    /// flushed — the distinction a caller checks before a serverless freeze.
    #[test]
    fn a_missed_deadline_is_never_reported_as_flushed() {
        let got = signal_flush_result(true, true, DrainOutcome::TimedOut);
        assert!(!got.flushed);
        assert!(got.timed_out);
        assert!(!got.failed);
    }

    /// An exporter that rejected the drain inside the deadline is failed and
    /// only failed: reporting it timed_out sends an operator tuning timeouts
    /// when the fix is a bad auth header or an unreachable collector.
    #[test]
    fn an_in_deadline_rejection_is_failed_never_timed_out() {
        let got = signal_flush_result(true, true, DrainOutcome::Failed);
        assert!(!got.flushed);
        assert!(!got.timed_out);
        assert!(got.failed);
    }

    /// The rejected check is per signal, like the abandoned one: a single
    /// rejecting exporter must turn `flush()` into an error.
    #[test]
    fn one_rejected_signal_is_enough_to_report_a_rejected_drain() {
        let clean = FlushResult {
            logs: drained(),
            traces: drained(),
            metrics: drained(),
        };
        assert!(!any_owned_drain_rejected(&clean));

        let rejected = SignalFlushResult {
            failed: true,
            ..SignalFlushResult::default()
        };
        for signal in ["logs", "traces", "metrics"] {
            let mut result = clean.clone();
            match signal {
                "logs" => result.logs = rejected,
                "traces" => result.traces = rejected,
                _ => result.metrics = rejected,
            }
            assert!(
                any_owned_drain_rejected(&result),
                "a rejected {signal} drain must be reported"
            );
        }
    }
}
