// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::sync::{OnceLock, RwLock};

use serde::{Deserialize, Serialize};

use crate::config::TelemetryConfig;
use crate::errors::TelemetryError;
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

pub(crate) fn provider_config_changed(current: &TelemetryConfig, target: &TelemetryConfig) -> bool {
    // Only compare fields that are provider-level (require process restart).
    // Exporter-level fields (endpoint, protocol) and hot-reloadable fields
    // (sampling, backpressure, etc.) are NOT compared here.
    current.service_name != target.service_name
        || current.environment != target.environment
        || current.version != target.version
        || current.logging.otlp_endpoint != target.logging.otlp_endpoint
        || current.logging.otlp_headers != target.logging.otlp_headers
        || current.tracing.enabled != target.tracing.enabled
        || current.tracing.otlp_endpoint != target.tracing.otlp_endpoint
        || current.tracing.otlp_headers != target.tracing.otlp_headers
        || current.metrics.enabled != target.metrics.enabled
        || current.metrics.otlp_endpoint != target.metrics.otlp_endpoint
        || current.metrics.otlp_headers != target.metrics.otlp_headers
}

pub fn get_runtime_config() -> Option<TelemetryConfig> {
    active_config()
        .read()
        .expect("runtime config lock poisoned")
        .clone()
}

fn runtime_config_snapshot() -> (Option<TelemetryConfig>, bool) {
    let guard = active_config()
        .read()
        .expect("runtime config lock poisoned");
    let cfg = guard.clone();
    (cfg.clone(), cfg.is_some())
}

pub fn get_runtime_status() -> RuntimeStatus {
    let (cfg, setup_done) = runtime_config_snapshot();
    let cfg = cfg.unwrap_or_else(|| TelemetryConfig::from_env().unwrap_or_default());

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

    let overrides = RuntimeOverrides {
        sampling: Some(fresh.sampling),
        backpressure: Some(fresh.backpressure),
        exporter: Some(fresh.exporter),
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

    if let Some(current) = get_runtime_config() {
        if otel_installed() && provider_config_changed(&current, &target) {
            return Err(TelemetryError::new(
                "OpenTelemetry providers already installed; restart the process for provider-changing config",
            ));
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
