// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::sync::{Mutex, OnceLock};

use tracing_subscriber::{
    layer::Layer as _, layer::SubscriberExt as _, util::SubscriberInitExt as _, Registry,
};

use crate::config::TelemetryConfig;
use crate::errors::TelemetryError;
use crate::otel::{build_otel_layer, build_otel_log_layer, setup_otel, shutdown_otel};
use crate::runtime::{get_runtime_config, set_active_config};

#[derive(Clone, Copy, Debug, Default)]
struct SetupState {
    done: bool,
}

static SETUP_STATE: OnceLock<Mutex<SetupState>> = OnceLock::new();

fn setup_state() -> &'static Mutex<SetupState> {
    SETUP_STATE.get_or_init(|| Mutex::new(SetupState::default()))
}

// Install the tracing subscriber stack. Uses try_init() so repeated calls
// after shutdown_telemetry() are silently ignored — the global subscriber
// cannot be uninstalled once set.
pub(crate) fn install_subscriber(config: &TelemetryConfig) {
    // Collect all layers as Box<dyn Layer<Registry>> so the Vec can be passed
    // to a single .with() call — avoids Layered<..., Layered<...>> type mismatches
    // that arise when chaining .with() calls with heterogeneous layer types.
    let mut layers: Vec<Box<dyn tracing_subscriber::Layer<Registry> + Send + Sync>> = Vec::new();

    layers.push(tracing_subscriber::EnvFilter::new(&config.logging.level).boxed());

    if config.logging.fmt == "json" {
        layers.push(tracing_subscriber::fmt::layer().json().boxed());
    } else {
        layers.push(tracing_subscriber::fmt::layer().boxed());
    }

    if let Some(otel) = build_otel_layer(config) {
        layers.push(otel);
    }

    if let Some(log_layer) = build_otel_log_layer(config) {
        layers.push(log_layer);
    }

    let _ = Registry::default().with(layers).try_init();
}

pub fn setup_telemetry() -> Result<TelemetryConfig, TelemetryError> {
    let mut state = setup_state().lock().expect("setup state lock poisoned");
    if state.done {
        return get_runtime_config()
            .ok_or_else(|| TelemetryError::new("telemetry setup state is inconsistent"));
    }

    let config = TelemetryConfig::from_env().map_err(|err| TelemetryError::new(err.message))?;
    install_subscriber(&config);
    setup_otel(&config)?;
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn setup_install_subscriber_is_idempotent() {
        let config = TelemetryConfig::default();
        // First call installs the subscriber; second call must not panic.
        install_subscriber(&config);
        install_subscriber(&config);
    }

    #[test]
    fn setup_install_subscriber_json_format_does_not_panic() {
        let mut config = TelemetryConfig::default();
        config.logging.fmt = "json".to_string();
        install_subscriber(&config);
    }
}
