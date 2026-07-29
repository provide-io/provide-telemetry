// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

//! Drain without teardown — force-flush installed providers, leave them installed.
//!
//! The drain half of the shutdown path. Each provider is cloned out of its slot
//! rather than taken, so telemetry keeps working afterwards, and each flush runs
//! under the bounded-shutdown deadline (see [`super::bounded_flush`]).

use std::sync::Arc;

use super::{logs, metrics, traces};

/// Force-flush the installed provider, leaving it installed and usable.
///
/// The drain half of the shutdown path: the provider is cloned out of its slot
/// rather than taken, so telemetry keeps working afterwards. Returns false when
/// the flush was abandoned at the bounded-shutdown deadline or the exporter
/// rejected it.
pub(crate) fn flush_logger_provider() -> bool {
    let provider = {
        let guard = crate::_lock::lock(logs::logger_provider_slot());
        guard
            .as_ref()
            .map(|installed| Arc::clone(&installed.provider))
    };
    let Some(provider) = provider else {
        return true;
    };

    super::bounded_flush("logs", move || provider.force_flush().is_ok())
}

/// Force-flush the installed provider, leaving it installed and usable.
///
/// The drain half of the shutdown path: the provider is cloned out of its slot
/// rather than taken, so telemetry keeps working afterwards. Returns false when
/// the flush was abandoned at the bounded-shutdown deadline or the exporter
/// rejected it.
pub(crate) fn flush_tracer_provider() -> bool {
    let provider = {
        let guard = crate::_lock::lock(traces::tracer_provider_slot());
        guard
            .as_ref()
            .map(|installed| Arc::clone(&installed.provider))
    };
    let Some(provider) = provider else {
        return true;
    };

    super::bounded_flush("traces", move || provider.force_flush().is_ok())
}

/// Force-flush the installed provider, leaving it installed and usable.
///
/// The drain half of the shutdown path: the provider is cloned out of its slot
/// rather than taken, so telemetry keeps working afterwards. Returns false when
/// the flush was abandoned at the bounded-shutdown deadline or the exporter
/// rejected it.
pub(crate) fn flush_meter_provider() -> bool {
    let provider = {
        let guard = crate::_lock::lock(metrics::meter_provider_slot());
        guard
            .as_ref()
            .map(|installed| Arc::clone(&installed.provider))
    };
    let Some(provider) = provider else {
        return true;
    };

    super::bounded_flush("metrics", move || provider.force_flush().is_ok())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::TelemetryConfig;
    use crate::testing::{acquire_test_state_lock, reset_telemetry_state};

    fn install_config() -> TelemetryConfig {
        // A syntactically valid endpoint that nothing listens on: the provider
        // installs, so the flush path runs against a real SDK provider, and the
        // export itself is irrelevant to what these tests pin.
        let mut cfg = TelemetryConfig {
            service_name: "flush-test".to_string(),
            ..TelemetryConfig::default()
        };
        cfg.tracing.enabled = true;
        cfg.tracing.otlp_endpoint = Some("http://127.0.0.1:4318/v1/traces".to_string());
        cfg.metrics.enabled = true;
        cfg.metrics.otlp_endpoint = Some("http://127.0.0.1:4318/v1/metrics".to_string());
        cfg.logging.otlp_endpoint = Some("http://127.0.0.1:4318/v1/logs".to_string());
        cfg
    }

    // Nothing installed is a drained state: the caller asked for the queue to be
    // empty and it is. Reporting failure here would make flush unusable in
    // cleanup paths that run before setup or after shutdown.
    #[test]
    fn flushing_with_no_provider_installed_succeeds() {
        let _guard = acquire_test_state_lock();
        reset_telemetry_state();

        assert!(flush_logger_provider());
        assert!(flush_tracer_provider());
        assert!(flush_meter_provider());
    }

    /// crate::flush_telemetry() must surface an incomplete drain as Err — the
    /// whole point of flush over shutdown is that the caller learns when its
    /// records did not make it out. Driven by a deadline no drain can meet
    /// rather than by an unreachable exporter, so the outcome does not depend
    /// on how a given SDK version reports an unreachable collector.
    #[test]
    fn flush_telemetry_reports_an_incomplete_drain_as_an_error() {
        let _guard = acquire_test_state_lock();
        reset_telemetry_state();

        let mut cfg = install_config();
        let resource = super::super::resource::build_resource(&cfg);
        let _ = super::super::traces::install_tracer_provider(&cfg, resource);

        // A deadline shorter than a thread spawn: the worker is always still
        // running when recv_timeout expires.
        cfg.exporter.logs_shutdown_timeout_seconds = 0.000_001;
        crate::runtime::set_active_config(Some(cfg));

        assert!(
            crate::flush_telemetry().is_err(),
            "a drain abandoned at its deadline must report Err"
        );

        crate::runtime::set_active_config(None);
        reset_telemetry_state();
    }

    // The installed path: each provider is cloned out of its slot rather than
    // taken, so the flush runs and the provider is still installed afterwards.
    // Without this the whole cloned-not-taken branch is unexercised.
    #[test]
    fn flushing_an_installed_provider_leaves_it_installed() {
        let _guard = acquire_test_state_lock();
        reset_telemetry_state();

        let cfg = install_config();
        let resource = super::super::resource::build_resource(&cfg);
        let _ = super::super::traces::install_tracer_provider(&cfg, resource.clone());
        let _ = super::super::metrics::install_meter_provider(&cfg, resource.clone());
        let _ = super::super::logs::install_logger_provider(&cfg, resource);

        // Each returns true: the drain completed inside the bounded deadline.
        assert!(flush_tracer_provider());
        assert!(flush_meter_provider());
        assert!(flush_logger_provider());

        // Still installed — that is the whole point of flush over shutdown.
        assert!(super::super::traces::tracer_provider_installed());
        assert!(super::super::metrics::meter_provider_installed());
        assert!(super::super::logs::logger_provider_installed());

        // And repeatable.
        assert!(flush_tracer_provider());
        assert!(flush_meter_provider());
        assert!(flush_logger_provider());

        reset_telemetry_state();
    }
}
