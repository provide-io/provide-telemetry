// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;
use std::sync::{Mutex, OnceLock};

use crate::backpressure::{set_queue_policy, QueuePolicy};
use crate::config::TelemetryConfig;
use crate::errors::TelemetryError;
use crate::otel::{setup_otel, shutdown_otel};
use crate::resilience::{set_exporter_policy, ExporterPolicy};
use crate::runtime::{get_runtime_config, set_active_config};
use crate::sampling::{set_sampling_policy, SamplingPolicy, Signal};

#[derive(Clone, Copy, Debug, Default)]
struct SetupState {
    done: bool,
}

static SETUP_STATE: OnceLock<Mutex<SetupState>> = OnceLock::new();

fn setup_state() -> &'static Mutex<SetupState> {
    SETUP_STATE.get_or_init(|| Mutex::new(SetupState::default()))
}

fn apply_policies(config: &TelemetryConfig) {
    let _ = set_sampling_policy(
        Signal::Logs,
        SamplingPolicy {
            default_rate: config.sampling.logs_rate,
            overrides: BTreeMap::new(),
        },
    );
    let _ = set_sampling_policy(
        Signal::Traces,
        SamplingPolicy {
            default_rate: config.sampling.traces_rate.min(config.tracing.sample_rate),
            overrides: BTreeMap::new(),
        },
    );
    let _ = set_sampling_policy(
        Signal::Metrics,
        SamplingPolicy {
            default_rate: config.sampling.metrics_rate,
            overrides: BTreeMap::new(),
        },
    );
    set_queue_policy(QueuePolicy {
        logs_maxsize: config.backpressure.logs_maxsize,
        traces_maxsize: config.backpressure.traces_maxsize,
        metrics_maxsize: config.backpressure.metrics_maxsize,
    });
    let _ = set_exporter_policy(
        Signal::Logs,
        ExporterPolicy {
            retries: config.exporter.logs_retries as u32,
            backoff_seconds: config.exporter.logs_backoff_seconds,
            timeout_seconds: config.exporter.logs_timeout_seconds,
            fail_open: config.exporter.logs_fail_open,
            allow_blocking_in_event_loop: false,
        },
    );
    let _ = set_exporter_policy(
        Signal::Traces,
        ExporterPolicy {
            retries: config.exporter.traces_retries as u32,
            backoff_seconds: config.exporter.traces_backoff_seconds,
            timeout_seconds: config.exporter.traces_timeout_seconds,
            fail_open: config.exporter.traces_fail_open,
            allow_blocking_in_event_loop: false,
        },
    );
    let _ = set_exporter_policy(
        Signal::Metrics,
        ExporterPolicy {
            retries: config.exporter.metrics_retries as u32,
            backoff_seconds: config.exporter.metrics_backoff_seconds,
            timeout_seconds: config.exporter.metrics_timeout_seconds,
            fail_open: config.exporter.metrics_fail_open,
            allow_blocking_in_event_loop: false,
        },
    );
}

pub fn setup_telemetry() -> Result<TelemetryConfig, TelemetryError> {
    let mut state = setup_state().lock().expect("setup state lock poisoned");
    if state.done {
        return get_runtime_config()
            .ok_or_else(|| TelemetryError::new("telemetry setup state is inconsistent"));
    }

    let config = TelemetryConfig::from_env().map_err(|err| TelemetryError::new(err.message))?;
    setup_otel(&config)?;
    apply_policies(&config);
    set_active_config(Some(config.clone()));
    state.done = true;
    Ok(config)
}

pub fn shutdown_telemetry() -> Result<(), TelemetryError> {
    let mut state = setup_state().lock().expect("setup state lock poisoned");
    state.done = false;
    shutdown_otel();
    set_active_config(None);
    Ok(())
}
