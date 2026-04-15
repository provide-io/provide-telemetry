// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::sync::{OnceLock, RwLock};

use serde::{Deserialize, Serialize};

use crate::config::TelemetryConfig;
use crate::errors::TelemetryError;
#[cfg(feature = "otel")]
use crate::otel::otel_installed;
use crate::policies::apply_policies;
use crate::RuntimeOverrides;

static ACTIVE_CONFIG: OnceLock<RwLock<Option<TelemetryConfig>>> = OnceLock::new();

fn active_config() -> &'static RwLock<Option<TelemetryConfig>> {
    ACTIVE_CONFIG.get_or_init(|| RwLock::new(None))
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SignalStatus {
    pub logs: bool,
    pub traces: bool,
    pub metrics: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuntimeStatus {
    pub setup_done: bool,
    pub signals: SignalStatus,
    pub providers: SignalStatus,
    pub fallback: SignalStatus,
    pub setup_error: Option<String>,
}

pub(crate) fn set_active_config(config: Option<TelemetryConfig>) {
    *active_config()
        .write()
        .expect("runtime config lock poisoned") = config;
}

/// Resource identity fields — baked into every installed provider's `Resource`.
/// A change here requires all live providers to be reinstalled.
#[cfg(any(feature = "otel", test))]
fn identity_config_changed(current: &TelemetryConfig, target: &TelemetryConfig) -> bool {
    current.service_name != target.service_name
        || current.environment != target.environment
        || current.version != target.version
}

/// Logging-signal fields baked into the log exporter/provider at construction.
#[cfg(any(feature = "otel", test))]
fn logging_provider_config_changed(current: &TelemetryConfig, target: &TelemetryConfig) -> bool {
    current.logging.otlp_endpoint != target.logging.otlp_endpoint
        || current.logging.otlp_headers != target.logging.otlp_headers
        || current.logging.otlp_protocol != target.logging.otlp_protocol
        || current.exporter.logs_timeout_seconds != target.exporter.logs_timeout_seconds
}

/// Tracing-signal fields baked into the span exporter/provider at construction.
#[cfg(any(feature = "otel", test))]
fn tracing_provider_config_changed(current: &TelemetryConfig, target: &TelemetryConfig) -> bool {
    current.tracing.enabled != target.tracing.enabled
        || current.tracing.otlp_endpoint != target.tracing.otlp_endpoint
        || current.tracing.otlp_headers != target.tracing.otlp_headers
        || current.tracing.otlp_protocol != target.tracing.otlp_protocol
        || current.exporter.traces_timeout_seconds != target.exporter.traces_timeout_seconds
}

/// Metrics-signal fields baked into the metric exporter/PeriodicReader at construction.
#[cfg(any(feature = "otel", test))]
fn metrics_provider_config_changed(current: &TelemetryConfig, target: &TelemetryConfig) -> bool {
    current.metrics.enabled != target.metrics.enabled
        || current.metrics.otlp_endpoint != target.metrics.otlp_endpoint
        || current.metrics.otlp_headers != target.metrics.otlp_headers
        || current.metrics.otlp_protocol != target.metrics.otlp_protocol
        || current.metrics.metric_export_interval_ms != target.metrics.metric_export_interval_ms
        || current.exporter.metrics_timeout_seconds != target.exporter.metrics_timeout_seconds
}

/// Returns `true` if any provider-baked field changed. Used in tests to
/// assert the full set of provider-changing fields; production code uses
/// the per-signal helpers directly inside `reconfigure_telemetry`.
#[cfg(test)]
pub(crate) fn provider_config_changed(current: &TelemetryConfig, target: &TelemetryConfig) -> bool {
    identity_config_changed(current, target)
        || logging_provider_config_changed(current, target)
        || tracing_provider_config_changed(current, target)
        || metrics_provider_config_changed(current, target)
}

pub fn get_runtime_config() -> Option<TelemetryConfig> {
    active_config()
        .read()
        .expect("runtime config lock poisoned")
        .clone()
}

pub fn get_runtime_status() -> RuntimeStatus {
    let cfg =
        get_runtime_config().unwrap_or_else(|| TelemetryConfig::from_env().unwrap_or_default());
    let setup_done = get_runtime_config().is_some();

    #[cfg(feature = "otel")]
    let providers = SignalStatus {
        logs: crate::otel::logs::logger_provider_installed(),
        traces: crate::otel::traces::tracer_provider_installed(),
        metrics: crate::otel::metrics::meter_provider_installed(),
    };

    #[cfg(not(feature = "otel"))]
    let providers = SignalStatus {
        logs: false,
        traces: false,
        metrics: false,
    };

    RuntimeStatus {
        setup_done,
        signals: SignalStatus {
            logs: true,
            traces: cfg.tracing.enabled,
            metrics: cfg.metrics.enabled,
        },
        fallback: SignalStatus {
            logs: !providers.logs,
            traces: !providers.traces,
            metrics: !providers.metrics,
        },
        providers,
        setup_error: crate::health::get_health_snapshot().setup_error,
    }
}

pub fn update_runtime_config(
    overrides: RuntimeOverrides,
) -> Result<TelemetryConfig, TelemetryError> {
    let next = {
        let mut guard = active_config()
            .write()
            .expect("runtime config lock poisoned");
        let current = guard.as_ref().cloned().ok_or_else(|| {
            TelemetryError::new("telemetry not set up: call setup_telemetry first")
        })?;
        let mut next = current;
        if let Some(sampling) = overrides.sampling {
            next.sampling = sampling;
        }
        if let Some(backpressure) = overrides.backpressure {
            next.backpressure = backpressure;
        }
        if let Some(exporter) = overrides.exporter {
            next.exporter = exporter;
        }
        if let Some(security) = overrides.security {
            next.security = security;
        }
        if let Some(slo) = overrides.slo {
            next.slo = slo;
        }
        if let Some(pii_max_depth) = overrides.pii_max_depth {
            next.pii_max_depth = pii_max_depth;
        }
        if let Some(strict_schema) = overrides.strict_schema {
            next.strict_schema = strict_schema;
        }
        if let Some(event_schema) = overrides.event_schema {
            next.event_schema = event_schema;
        }
        *guard = Some(next.clone());
        next
    }; // write lock released here before calling apply_policies
    apply_policies(&next);
    Ok(next)
}

pub fn reload_runtime_from_env() -> Result<TelemetryConfig, TelemetryError> {
    let fresh = TelemetryConfig::from_env().map_err(|err| TelemetryError::new(err.message))?;
    let current = get_runtime_config()
        .ok_or_else(|| TelemetryError::new("telemetry not set up: call setup_telemetry first"))?;

    // Warn on cold-field drift (matches Python/TypeScript/Go behavior).
    let mut drifted: Vec<&str> = Vec::new();
    if current.service_name != fresh.service_name {
        drifted.push("service_name");
    }
    if current.environment != fresh.environment {
        drifted.push("environment");
    }
    if current.version != fresh.version {
        drifted.push("version");
    }
    if current.tracing.enabled != fresh.tracing.enabled {
        drifted.push("tracing.enabled");
    }
    if current.metrics.enabled != fresh.metrics.enabled {
        drifted.push("metrics.enabled");
    }
    if !drifted.is_empty() {
        eprintln!(
            "[provide-telemetry] runtime.cold_field_drift: {} — restart required to apply",
            drifted.join(", ")
        );
    }

    // Exporter timeout fields are baked into OTLP exporters at construction
    // time.  Only freeze them per-signal when the signal's OTel provider is
    // actually live — otherwise they remain hot-reloadable.  Preserving them
    // *before* update_runtime_config ensures apply_policies() and the stored
    // snapshot always agree (no split-brain).
    #[allow(unused_mut)] // `mut` is only exercised when the `otel` feature is enabled
    let mut hot_exporter = fresh.exporter;
    #[cfg(feature = "otel")]
    {
        if crate::otel::logs::logger_provider_installed() {
            hot_exporter.logs_timeout_seconds = current.exporter.logs_timeout_seconds;
        }
        if crate::otel::traces::tracer_provider_installed() {
            hot_exporter.traces_timeout_seconds = current.exporter.traces_timeout_seconds;
        }
        if crate::otel::metrics::meter_provider_installed() {
            hot_exporter.metrics_timeout_seconds = current.exporter.metrics_timeout_seconds;
        }
    }

    let overrides = RuntimeOverrides {
        sampling: Some(fresh.sampling),
        backpressure: Some(fresh.backpressure),
        exporter: Some(hot_exporter),
        security: Some(fresh.security),
        slo: Some(fresh.slo),
        pii_max_depth: Some(fresh.pii_max_depth),
        strict_schema: Some(fresh.strict_schema),
        event_schema: Some(fresh.event_schema),
    };

    let mut next = update_runtime_config(overrides)?;
    next.service_name = current.service_name;
    next.environment = current.environment;
    next.version = current.version;
    next.logging.level = current.logging.level;
    next.logging.fmt = current.logging.fmt;
    next.logging.otlp_headers = current.logging.otlp_headers;
    next.tracing.enabled = current.tracing.enabled;
    next.tracing.otlp_headers = current.tracing.otlp_headers;
    next.metrics.enabled = current.metrics.enabled;
    next.metrics.otlp_headers = current.metrics.otlp_headers;

    set_active_config(Some(next.clone()));
    Ok(next)
}

pub fn reconfigure_telemetry(
    config: Option<TelemetryConfig>,
) -> Result<TelemetryConfig, TelemetryError> {
    let target = match config {
        Some(config) => config,
        None => TelemetryConfig::from_env().map_err(|err| TelemetryError::new(err.message))?,
    };

    #[cfg(feature = "otel")]
    if let Some(current) = get_runtime_config() {
        if otel_installed() {
            let logs_live = crate::otel::logs::logger_provider_installed();
            let traces_live = crate::otel::traces::tracer_provider_installed();
            let metrics_live = crate::otel::metrics::meter_provider_installed();
            // Identity fields affect every installed provider's Resource; per-signal
            // fields only matter when that signal's provider is actually live.
            let reject = ((logs_live || traces_live || metrics_live)
                && identity_config_changed(&current, &target))
                || (logs_live && logging_provider_config_changed(&current, &target))
                || (traces_live && tracing_provider_config_changed(&current, &target))
                || (metrics_live && metrics_provider_config_changed(&current, &target));
            if reject {
                return Err(TelemetryError::new(
                    "OpenTelemetry providers already installed; restart the process for provider-changing config",
                ));
            }
        }
    }

    set_active_config(Some(target.clone()));
    apply_policies(&target);
    Ok(target)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runtime_test_provider_config_changed_detects_each_provider_field() {
        let current = TelemetryConfig::default();

        let mut changed = current.clone();
        changed.service_name = "svc-2".to_string();
        assert!(provider_config_changed(&current, &changed));

        let mut changed = current.clone();
        changed.environment = "prod".to_string();
        assert!(provider_config_changed(&current, &changed));

        let mut changed = current.clone();
        changed.version = "1.2.3".to_string();
        assert!(provider_config_changed(&current, &changed));

        let mut changed = current.clone();
        changed.logging.otlp_headers.insert("x".into(), "1".into());
        assert!(provider_config_changed(&current, &changed));

        let mut changed = current.clone();
        changed.tracing.enabled = !changed.tracing.enabled;
        assert!(provider_config_changed(&current, &changed));

        let mut changed = current.clone();
        changed.metrics.enabled = !changed.metrics.enabled;
        assert!(provider_config_changed(&current, &changed));

        let mut changed = current.clone();
        changed.logging.otlp_endpoint = Some("http://other:4318".into());
        assert!(provider_config_changed(&current, &changed));

        let mut changed = current.clone();
        changed.tracing.otlp_endpoint = Some("http://other:4318".into());
        assert!(provider_config_changed(&current, &changed));

        let mut changed = current.clone();
        changed.metrics.otlp_endpoint = Some("http://other:4318".into());
        assert!(provider_config_changed(&current, &changed));

        // --- headers (all three signals) ---
        let mut changed = current.clone();
        changed
            .tracing
            .otlp_headers
            .insert("auth".into(), "tok".into());
        assert!(provider_config_changed(&current, &changed));

        let mut changed = current.clone();
        changed
            .metrics
            .otlp_headers
            .insert("auth".into(), "tok".into());
        assert!(provider_config_changed(&current, &changed));

        // --- protocol (all three signals) ---
        let mut changed = current.clone();
        changed.logging.otlp_protocol = "http/json".to_string();
        assert!(provider_config_changed(&current, &changed));

        let mut changed = current.clone();
        changed.tracing.otlp_protocol = "http/json".to_string();
        assert!(provider_config_changed(&current, &changed));

        let mut changed = current.clone();
        changed.metrics.otlp_protocol = "http/json".to_string();
        assert!(provider_config_changed(&current, &changed));

        // --- exporter timeouts (baked into exporter at construction) ---
        let mut changed = current.clone();
        changed.exporter.logs_timeout_seconds = 5.0;
        assert!(provider_config_changed(&current, &changed));

        let mut changed = current.clone();
        changed.exporter.traces_timeout_seconds = 5.0;
        assert!(provider_config_changed(&current, &changed));

        let mut changed = current.clone();
        changed.exporter.metrics_timeout_seconds = 5.0;
        assert!(provider_config_changed(&current, &changed));

        // --- metrics export interval (baked into PeriodicReader) ---
        let mut changed = current.clone();
        changed.metrics.metric_export_interval_ms = 30_000;
        assert!(provider_config_changed(&current, &changed));
    }

    #[test]
    fn runtime_test_provider_config_changed_is_false_for_hot_only_changes() {
        let current = TelemetryConfig::default();
        let mut changed = current.clone();
        changed.sampling.logs_rate = 0.25;
        changed.backpressure.logs_maxsize = 9;
        changed.exporter.logs_retries = 2;
        changed.security.max_attr_count = 99;
        changed.slo.enable_red_metrics = !changed.slo.enable_red_metrics;
        changed.pii_max_depth = 3;
        changed.strict_schema = true;

        assert!(!provider_config_changed(&current, &changed));
    }

    #[test]
    fn runtime_test_per_signal_helpers_are_independent() {
        let base = TelemetryConfig::default();

        // logging-only change — only logging helper fires
        let mut changed = base.clone();
        changed.logging.otlp_protocol = "http/json".to_string();
        assert!(logging_provider_config_changed(&base, &changed));
        assert!(!tracing_provider_config_changed(&base, &changed));
        assert!(!metrics_provider_config_changed(&base, &changed));

        // tracing-only change — only tracing helper fires
        let mut changed = base.clone();
        changed.exporter.traces_timeout_seconds = 5.0;
        assert!(!logging_provider_config_changed(&base, &changed));
        assert!(tracing_provider_config_changed(&base, &changed));
        assert!(!metrics_provider_config_changed(&base, &changed));

        // metrics-only change — only metrics helper fires
        let mut changed = base.clone();
        changed.metrics.metric_export_interval_ms = 30_000;
        assert!(!logging_provider_config_changed(&base, &changed));
        assert!(!tracing_provider_config_changed(&base, &changed));
        assert!(metrics_provider_config_changed(&base, &changed));
    }

    #[test]
    fn runtime_test_reload_timeout_hot_when_no_provider_snapshot_matches_live_policy() {
        // Serialize against other tests that touch env or runtime state.
        let _guard = crate::testing::acquire_test_state_lock();
        use std::env;

        // Set up with a known timeout.
        env::set_var("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS", "7.0");
        env::set_var("PROVIDE_SAMPLING_LOGS_RATE", "1.0");
        set_active_config(Some(
            TelemetryConfig::from_env().expect("config must parse"),
        ));
        apply_policies(&get_runtime_config().expect("config must exist"));

        // No OTel provider is installed in this unit-test environment, so the
        // timeout field is hot-reloadable.  Change it and reload.
        env::set_var("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS", "99.0");
        env::set_var("PROVIDE_SAMPLING_LOGS_RATE", "0.5");

        let reloaded = reload_runtime_from_env().expect("reload must succeed");

        // Without a live provider, timeout IS hot-reloadable.
        assert_eq!(
            reloaded.exporter.logs_timeout_seconds, 99.0,
            "timeout must be hot-reloadable when no OTel provider is installed"
        );

        // The key invariant: config snapshot and live exporter policy agree —
        // no split-brain regardless of which path (freeze or update) was taken.
        let policy = crate::resilience::get_exporter_policy(crate::sampling::Signal::Logs)
            .expect("policy must exist");
        assert_eq!(
            policy.timeout_seconds, reloaded.exporter.logs_timeout_seconds,
            "live exporter policy must match the config snapshot (no split-brain)"
        );

        // Hot-reloadable non-timeout field also updated correctly.
        assert_eq!(
            reloaded.sampling.logs_rate, 0.5,
            "sampling rate must update"
        );

        // Cleanup: remove env vars and reset all global telemetry state so
        // subsequent tests (sampling, backpressure, schema, resilience, etc.)
        // start from a known clean slate.
        env::remove_var("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS");
        env::remove_var("PROVIDE_SAMPLING_LOGS_RATE");
        crate::testing::reset_telemetry_state();
    }

    #[test]
    fn runtime_test_runtime_config_snapshot_reports_cfg_and_setup_done_from_one_read() {
        set_active_config(None);
        let (cfg, setup_done) = runtime_config_snapshot();
        assert!(cfg.is_none());
        assert!(!setup_done);

        let configured = TelemetryConfig::default();
        set_active_config(Some(configured.clone()));
        let (cfg, setup_done) = runtime_config_snapshot();
        assert_eq!(cfg, Some(configured));
        assert!(setup_done);
    }
}
