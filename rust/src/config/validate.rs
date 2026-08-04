// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Range checks for a [`TelemetryConfig`] that did not come from the environment.
//!
//! `TelemetryConfig::from_env` validates as it parses, so every field it
//! produces is already in range. A config handed to `setup_telemetry(Some(cfg))`
//! has been through no such check, and the policy installers downstream *clamp*
//! rather than reject: `set_sampling_policy` silently pins a rate of 2.0 to 1.0
//! while `get_runtime_config` keeps reporting 2.0. A caller reading the runtime
//! snapshot back would be told a sampling rate that is not the one in force.
//!
//! Rejecting up front keeps the snapshot and the installed policy the same
//! thing, and matches what the other three languages do with an explicit config.

use super::TelemetryConfig;
use crate::errors::ConfigurationError;

fn require_rate(field: &str, value: f64) -> Result<(), ConfigurationError> {
    if !value.is_finite() || !(0.0..=1.0).contains(&value) {
        return Err(ConfigurationError::new(format!(
            "{field} must be in [0, 1], got {value}"
        )));
    }
    Ok(())
}

fn require_non_negative(field: &str, value: f64) -> Result<(), ConfigurationError> {
    if !value.is_finite() || value < 0.0 {
        return Err(ConfigurationError::new(format!(
            "{field} must be >= 0, got {value}"
        )));
    }
    Ok(())
}

/// Retries above the ceiling are silently meaningless — the resilience layer
/// caps attempts at `MAX_EXPORTER_RETRIES + 1` — so reject them, exactly as
/// `from_env` and TypeScript's `requireRetries` do.
fn require_retries(field: &str, value: usize) -> Result<(), ConfigurationError> {
    if value > super::MAX_EXPORTER_RETRIES {
        return Err(ConfigurationError::new(format!(
            "{field} must be at most {}, got {value}",
            super::MAX_EXPORTER_RETRIES
        )));
    }
    Ok(())
}

impl TelemetryConfig {
    /// Check every numeric field `from_env` would have rejected.
    ///
    /// Field names in the messages are the environment variables a caller would
    /// recognise, so an explicit config and a mis-set environment report the
    /// same problem the same way.
    pub(crate) fn validate(&self) -> Result<(), ConfigurationError> {
        require_rate("PROVIDE_SAMPLING_LOGS_RATE", self.sampling.logs_rate)?;
        require_rate("PROVIDE_SAMPLING_TRACES_RATE", self.sampling.traces_rate)?;
        require_rate("PROVIDE_SAMPLING_METRICS_RATE", self.sampling.metrics_rate)?;
        require_rate("PROVIDE_TRACE_SAMPLE_RATE", self.tracing.sample_rate)?;
        require_non_negative(
            "PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS",
            self.exporter.logs_backoff_seconds,
        )?;
        require_non_negative(
            "PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS",
            self.exporter.traces_backoff_seconds,
        )?;
        require_non_negative(
            "PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS",
            self.exporter.metrics_backoff_seconds,
        )?;
        require_non_negative(
            "PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS",
            self.exporter.logs_timeout_seconds,
        )?;
        require_non_negative(
            "PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS",
            self.exporter.traces_timeout_seconds,
        )?;
        require_non_negative(
            "PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS",
            self.exporter.metrics_timeout_seconds,
        )?;
        require_non_negative(
            "PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS",
            self.exporter.logs_shutdown_timeout_seconds,
        )?;
        require_retries("PROVIDE_EXPORTER_LOGS_RETRIES", self.exporter.logs_retries)?;
        require_retries(
            "PROVIDE_EXPORTER_TRACES_RETRIES",
            self.exporter.traces_retries,
        )?;
        require_retries(
            "PROVIDE_EXPORTER_METRICS_RETRIES",
            self.exporter.metrics_retries,
        )?;
        Ok(())
    }
}

#[cfg(test)]
#[path = "validate_tests.rs"]
mod validate_tests;
