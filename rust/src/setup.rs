// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::sync::{Mutex, OnceLock};

use crate::config::TelemetryConfig;
use crate::errors::TelemetryError;
use crate::otel::{setup_otel, shutdown_otel};
use crate::runtime::{get_runtime_config, set_active_config};

#[derive(Clone, Copy, Debug, Default)]
struct SetupState {
    done: bool,
}

static SETUP_STATE: OnceLock<Mutex<SetupState>> = OnceLock::new();

fn setup_state() -> &'static Mutex<SetupState> {
    SETUP_STATE.get_or_init(|| Mutex::new(SetupState::default()))
}

pub fn setup_telemetry() -> Result<TelemetryConfig, TelemetryError> {
    let mut state = setup_state().lock().expect("setup state lock poisoned");
    if state.done {
        return get_runtime_config()
            .ok_or_else(|| TelemetryError::new("telemetry setup state is inconsistent"));
    }

    let config = TelemetryConfig::from_env().map_err(|err| TelemetryError::new(err.message))?;
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
