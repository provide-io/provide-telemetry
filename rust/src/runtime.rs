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
#[cfg(feature = "otel")]
const PROVIDER_CHANGE_RESTART_MESSAGE: &str =
    "OpenTelemetry providers already installed; restart the process for provider-changing config";

fn empty_active_config() -> RwLock<Option<TelemetryConfig>> {
    RwLock::new(None)
}

fn active_config() -> &'static RwLock<Option<TelemetryConfig>> {
    ACTIVE_CONFIG.get_or_init(empty_active_config)
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
    *crate::_lock::rwlock_write(active_config()) = config;
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
    crate::_lock::rwlock_read(active_config()).clone()
}

fn runtime_config_snapshot() -> (Option<TelemetryConfig>, bool) {
    let guard = crate::_lock::rwlock_read(active_config());
    let cfg = guard.clone();
    (cfg.clone(), cfg.is_some())
}

pub fn get_runtime_status() -> RuntimeStatus {
    let (cfg, setup_done) = runtime_config_snapshot();
    let cfg = runtime_config_or_default(cfg);

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
    let logging_override = overrides.logging.clone();
    let next = {
        let mut guard = crate::_lock::rwlock_write(active_config());
        let current = match guard.as_ref().cloned() {
            Some(current) => current,
            None => {
                return Err(TelemetryError::new(
                    "telemetry not set up: call setup_telemetry first",
                ));
            }
        };
        let next = apply_runtime_overrides(current, overrides);
        *guard = Some(next.clone());
        next
    }; // write lock released here before calling apply_policies
    apply_policies(&next);
    // When the caller supplies a logging override, mirror Python's behavior:
    // reconfigure the logger so level/format/module-level changes take effect
    // on the next log event.  The logger's `active_logging_config()` already
    // prefers the programmatic override over runtime config, so this makes
    // the override win consistently across both read paths.
    if let Some(cfg) = logging_override {
        crate::logger::configure_logging(cfg);
    }
    Ok(next)
}

pub fn reload_runtime_from_env() -> Result<TelemetryConfig, TelemetryError> {
    let fresh = match TelemetryConfig::from_env() {
        Ok(fresh) => fresh,
        Err(err) => return Err(TelemetryError::new(err.message)),
    };
    let current = match get_runtime_config() {
        Some(current) => current,
        None => {
            return Err(TelemetryError::new(
                "telemetry not set up: call setup_telemetry first",
            ))
        }
    };

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

    // Logging: level / fmt / include_timestamp / module_levels are hot.
    // `otlp_endpoint`, `otlp_headers`, and `otlp_protocol` are baked into the
    // OTLP log exporter at construction — freeze them from `current` when the
    // log provider is live so env drift on those fields can't silently
    // diverge from the installed exporter.
    #[allow(unused_mut)] // `mut` is only exercised when the `otel` feature is enabled
    let mut hot_logging = fresh.logging.clone();
    #[cfg(feature = "otel")]
    {
        if crate::otel::logs::logger_provider_installed() {
            hot_logging.otlp_endpoint = current.logging.otlp_endpoint.clone();
            hot_logging.otlp_headers = current.logging.otlp_headers.clone();
            hot_logging.otlp_protocol = current.logging.otlp_protocol.clone();
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
        logging: Some(hot_logging),
    };

    let mut next = apply_runtime_overrides(current.clone(), overrides);
    set_active_config(Some(next.clone()));
    apply_policies(&next);
    // Reconfigure the logger so env-driven level / fmt / module-level drift
    // takes effect on the next log event (mirrors Python parity).
    crate::logger::configure_logging(next.logging.clone());
    next.service_name = current.service_name;
    next.environment = current.environment;
    next.version = current.version;
    next.tracing.enabled = current.tracing.enabled;
    next.tracing.otlp_headers = current.tracing.otlp_headers;
    next.metrics.enabled = current.metrics.enabled;
    next.metrics.otlp_headers = current.metrics.otlp_headers;

    set_active_config(Some(next.clone()));
    Ok(next)
}

fn apply_runtime_overrides(
    current: TelemetryConfig,
    overrides: RuntimeOverrides,
) -> TelemetryConfig {
    let mut next = current;
    next.sampling = overrides.sampling.unwrap_or(next.sampling);
    next.backpressure = overrides.backpressure.unwrap_or(next.backpressure);
    next.exporter = overrides.exporter.unwrap_or(next.exporter);
    next.security = overrides.security.unwrap_or(next.security);
    next.slo = overrides.slo.unwrap_or(next.slo);
    next.pii_max_depth = overrides.pii_max_depth.unwrap_or(next.pii_max_depth);
    next.strict_schema = overrides.strict_schema.unwrap_or(next.strict_schema);
    next.event_schema = overrides.event_schema.unwrap_or(next.event_schema);
    next.logging = overrides.logging.unwrap_or(next.logging);
    next
}

fn runtime_config_or_default(config: Option<TelemetryConfig>) -> TelemetryConfig {
    match config {
        Some(config) => config,
        None => TelemetryConfig::from_env().unwrap_or_default(),
    }
}

pub fn reconfigure_telemetry(
    config: Option<TelemetryConfig>,
) -> Result<TelemetryConfig, TelemetryError> {
    let target = match config {
        Some(config) => config,
        None => match TelemetryConfig::from_env() {
            Ok(config) => config,
            Err(err) => return Err(TelemetryError::new(err.message)),
        },
    };

    #[cfg(feature = "otel")]
    if let Some(current) = get_runtime_config() {
        if otel_installed() {
            let logs_live = crate::otel::logs::logger_provider_installed();
            let traces_live = crate::otel::traces::tracer_provider_installed();
            let metrics_live = crate::otel::metrics::meter_provider_installed();
            // Identity fields affect every installed provider's Resource; per-signal
            // fields only matter when that signal's provider is actually live.
            let reject = identity_config_changed(&current, &target)
                || (logs_live && logging_provider_config_changed(&current, &target))
                || (traces_live && tracing_provider_config_changed(&current, &target))
                || (metrics_live && metrics_provider_config_changed(&current, &target));
            if reject {
                Err(TelemetryError::new(PROVIDER_CHANGE_RESTART_MESSAGE))
            } else {
                Ok(())
            }?;
        }
    }

    set_active_config(Some(target.clone()));
    apply_policies(&target);
    Ok(target)
}

#[cfg(test)]
#[path = "runtime_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "runtime_logging_tests.rs"]
mod logging_tests;
