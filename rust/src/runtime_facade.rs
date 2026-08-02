// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use serde::{Deserialize, Serialize};

use crate::config::{RuntimeOverrides, TelemetryConfig};
use crate::errors::TelemetryError;

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

/// One signal's flush outcome, from what is installed, what we own, and whether
/// it drained.
///
/// A free function rather than a closure inside `flush` so it is reachable
/// without a live provider: in a build with no OTel providers installed, only
/// the `not_installed` arm of the inline version ever ran, leaving the rest
/// untested. Mirrors Python's `_signal_flush_result`.
///
/// A signal with no provider has nothing to drain. A signal whose provider was
/// adopted from the OTel globals belongs to the host — we leave it alone, so
/// calling it `flushed` would claim records are out while they sit in the
/// host's batch processor.
fn signal_flush_result(installed: bool, owned: bool, drained: bool) -> SignalFlushResult {
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
        flushed: drained,
        timed_out: !drained,
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
    pub fn flush(&self, timeout_seconds: Option<f64>) -> Result<FlushResult, TelemetryError> {
        let providers = crate::runtime::get_runtime_status().providers;
        let owned = crate::otel::owned_signals();
        let drained = crate::otel::flush_otel_by_signal(timeout_seconds);
        Ok(FlushResult {
            logs: signal_flush_result(providers.logs, owned.logs, drained.logs),
            traces: signal_flush_result(providers.traces, owned.traces, drained.traces),
            metrics: signal_flush_result(providers.metrics, owned.metrics, drained.metrics),
        })
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
    use super::{signal_flush_result, SignalFlushResult};

    /// The full truth table. Each row is a distinct answer a caller acts on:
    /// nothing to drain, not ours to drain, drained, or missed the deadline.
    #[test]
    fn covers_every_combination() {
        let cases: [(bool, bool, bool, SignalFlushResult); 5] = [
            (
                false,
                false,
                true,
                SignalFlushResult {
                    not_installed: true,
                    ..SignalFlushResult::default()
                },
            ),
            (
                false,
                true,
                true,
                SignalFlushResult {
                    not_installed: true,
                    ..SignalFlushResult::default()
                },
            ),
            (
                true,
                false,
                true,
                SignalFlushResult {
                    not_owned: true,
                    ..SignalFlushResult::default()
                },
            ),
            (
                true,
                true,
                true,
                SignalFlushResult {
                    flushed: true,
                    ..SignalFlushResult::default()
                },
            ),
            (
                true,
                true,
                false,
                SignalFlushResult {
                    timed_out: true,
                    ..SignalFlushResult::default()
                },
            ),
        ];

        for (installed, owned, drained, want) in cases {
            let got = signal_flush_result(installed, owned, drained);
            assert_eq!(
                got, want,
                "installed={installed} owned={owned} drained={drained}"
            );
        }
    }

    /// not_installed wins over not_owned: a signal with no provider at all is
    /// not "the host's to drain", it is simply absent.
    #[test]
    fn not_installed_takes_precedence_over_not_owned() {
        let got = signal_flush_result(false, false, false);
        assert!(got.not_installed);
        assert!(!got.not_owned);
        assert!(!got.flushed);
        assert!(!got.timed_out);
    }

    /// An owned, installed signal that missed its deadline is timed_out, never
    /// flushed — the distinction a caller checks before a serverless freeze.
    #[test]
    fn a_missed_deadline_is_never_reported_as_flushed() {
        let got = signal_flush_result(true, true, false);
        assert!(!got.flushed);
        assert!(got.timed_out);
        assert!(!got.failed);
    }
}
