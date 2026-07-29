// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::sync::{Mutex, OnceLock};

use crate::config::TelemetryConfig;
use crate::errors::TelemetryError;
use crate::otel::{flush_otel, setup_otel, shutdown_otel};
use crate::policies::apply_policies;
use crate::runtime::{get_runtime_config, set_active_config};

#[derive(Clone, Copy, Debug, Default)]
struct SetupState {
    done: bool,
}

static SETUP_STATE: OnceLock<Mutex<SetupState>> = OnceLock::new();

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only swap in Mutex::default().
fn default_setup_state_mutex() -> Mutex<SetupState> {
    Mutex::new(SetupState::default())
}

fn setup_state() -> &'static Mutex<SetupState> {
    SETUP_STATE.get_or_init(default_setup_state_mutex)
}

pub fn setup_telemetry() -> Result<TelemetryConfig, TelemetryError> {
    let mut state = crate::_lock::lock(setup_state());
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

/// Force-flush installed providers without tearing them down.
///
/// The drain half of [`shutdown_telemetry`]: every provider we installed is
/// force-flushed under the bounded-shutdown deadline
/// (`PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS`) and stays installed and
/// usable. Use it where records must be out before control returns — a request
/// boundary, a checkpoint, a serverless freeze — rather than shutting telemetry
/// down and paying to set it up again.
///
/// Returns `Ok(())` when every signal drained within the deadline (including
/// when nothing is installed) and `Err` when any was abandoned, so a caller
/// flushing to be sure its records are out learns when they are not.
pub fn flush_telemetry() -> Result<(), TelemetryError> {
    if flush_otel() {
        return Ok(());
    }
    Err(TelemetryError::new(
        "telemetry flush exceeded its deadline; records may not have been exported",
    ))
}

pub fn shutdown_telemetry() -> Result<(), TelemetryError> {
    {
        let mut state = crate::_lock::lock(setup_state());
        state.done = false;
    }
    shutdown_otel();
    set_active_config(None);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    use crate::testing::acquire_test_state_lock;

    #[test]
    fn flush_is_ok_when_nothing_is_installed() {
        let _guard = acquire_test_state_lock();
        shutdown_telemetry().expect("pre-test shutdown should succeed");

        // Nothing installed means nothing to drain — a successful no-op, not
        // an error, so callers can flush unconditionally.
        flush_telemetry().expect("flush with no providers should succeed");
    }

    #[test]
    fn flush_leaves_telemetry_set_up_and_repeatable() {
        let _guard = acquire_test_state_lock();
        shutdown_telemetry().expect("pre-test shutdown should succeed");
        let config = setup_telemetry().expect("setup should succeed");

        flush_telemetry().expect("first flush should succeed");
        flush_telemetry().expect("second flush should succeed");

        // Unlike shutdown, flush must leave the active runtime config in place.
        assert_eq!(
            get_runtime_config().expect("runtime config should survive a flush"),
            config
        );
        shutdown_telemetry().expect("shutdown should succeed");
    }

    #[test]
    fn setup_test_round_trip_sets_and_clears_runtime_state() {
        let _guard = acquire_test_state_lock();
        shutdown_telemetry().expect("pre-test shutdown should succeed");

        let config = setup_telemetry().expect("setup should succeed");
        assert_eq!(
            get_runtime_config().expect("runtime config should exist"),
            config
        );
        assert!(crate::_lock::lock(setup_state()).done);

        shutdown_telemetry().expect("shutdown should succeed");
        assert!(get_runtime_config().is_none());
        assert!(!crate::_lock::lock(setup_state()).done);
    }

    #[test]
    fn setup_test_repeated_setup_returns_existing_runtime_config() {
        let _guard = acquire_test_state_lock();
        shutdown_telemetry().expect("pre-test shutdown should succeed");

        let first = setup_telemetry().expect("first setup should succeed");
        let second = setup_telemetry().expect("second setup should return existing config");

        assert_eq!(first, second);
        shutdown_telemetry().expect("shutdown should succeed");
    }

    #[test]
    fn setup_test_inconsistent_done_state_returns_error() {
        let _guard = acquire_test_state_lock();
        shutdown_telemetry().expect("pre-test shutdown should succeed");
        set_active_config(None);
        crate::_lock::lock(setup_state()).done = true;

        let err = setup_telemetry().expect_err("inconsistent state must fail");
        assert!(
            err.message.contains("inconsistent"),
            "unexpected error: {}",
            err.message
        );

        crate::_lock::lock(setup_state()).done = false;
    }

    #[test]
    fn setup_test_invalid_env_surfaces_parse_error() {
        let _guard = acquire_test_state_lock();
        shutdown_telemetry().expect("pre-test shutdown should succeed");
        std::env::set_var("PROVIDE_LOG_INCLUDE_TIMESTAMP", "not-a-bool");

        let err = setup_telemetry().expect_err("invalid env must fail setup");
        assert!(err.message.contains("PROVIDE_LOG_INCLUDE_TIMESTAMP"));

        std::env::remove_var("PROVIDE_LOG_INCLUDE_TIMESTAMP");
    }

    #[cfg(feature = "otel")]
    #[test]
    fn setup_test_invalid_otel_endpoint_surfaces_setup_error() {
        let _guard = acquire_test_state_lock();
        shutdown_telemetry().expect("pre-test shutdown should succeed");
        std::env::set_var("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "ftp://collector:4318");
        std::env::set_var("PROVIDE_EXPORTER_LOGS_FAIL_OPEN", "false");

        let err = setup_telemetry().expect_err("invalid OTEL endpoint must fail setup");
        assert!(err.message.contains("scheme"));

        std::env::remove_var("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT");
        std::env::remove_var("PROVIDE_EXPORTER_LOGS_FAIL_OPEN");
    }
}
