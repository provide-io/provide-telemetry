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

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
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
    pub fn start(&mut self, config: Option<TelemetryConfig>) -> Result<TelemetryConfig, TelemetryError> {
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
    pub fn flush(&self, timeout_seconds: Option<f64>) -> Result<FlushResult, TelemetryError> {
        let providers = crate::runtime::get_runtime_status().providers;
        crate::setup::flush_telemetry(timeout_seconds)?;
        let result_for = |installed| SignalFlushResult {
            flushed: installed,
            not_installed: !installed,
            not_owned: false,
            timed_out: false,
            failed: false,
        };
        Ok(FlushResult {
            logs: result_for(providers.logs),
            traces: result_for(providers.traces),
            metrics: result_for(providers.metrics),
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
