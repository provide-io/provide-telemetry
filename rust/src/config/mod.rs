// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::HashMap;
use std::env;

use serde::{Deserialize, Serialize};

use crate::errors::ConfigurationError;

mod parse;
mod redact;

use parse::{
    env_value, parse_bool, parse_non_negative_float, parse_otlp_headers, parse_rate, parse_usize,
};
pub use redact::redact_config;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Default)]
pub struct RuntimeOverrides {
    pub sampling: Option<SamplingConfig>,
    pub backpressure: Option<BackpressureConfig>,
    pub exporter: Option<ExporterPolicyConfig>,
    pub security: Option<SecurityConfig>,
    pub slo: Option<SLOConfig>,
    pub pii_max_depth: Option<usize>,
    pub strict_schema: Option<bool>,
    pub event_schema: Option<EventSchemaConfig>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct LoggingConfig {
    pub level: String,
    pub fmt: String,
    /// Whether to include an ISO 8601 timestamp in JSON log output.
    /// Controlled by `PROVIDE_LOG_INCLUDE_TIMESTAMP` (default: true).
    pub include_timestamp: bool,
    pub otlp_headers: HashMap<String, String>,
    /// OTLP endpoint URL for logs export. Falls back to the shared
    /// `OTEL_EXPORTER_OTLP_ENDPOINT` when `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT`
    /// is unset. `None` means no endpoint configured.
    pub otlp_endpoint: Option<String>,
    /// OTLP transport protocol for logs. Empty string means default
    /// (resolved at exporter-build time to `http/protobuf`). Values:
    /// `http/protobuf`, `http/json`, `grpc` (the latter requires the
    /// `otel-grpc` cargo feature).
    pub otlp_protocol: String,
}

impl Default for LoggingConfig {
    fn default() -> Self {
        Self {
            level: "INFO".to_string(),
            fmt: "console".to_string(),
            include_timestamp: true,
            otlp_headers: HashMap::new(),
            otlp_endpoint: None,
            otlp_protocol: String::new(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TracingConfig {
    pub enabled: bool,
    /// Per-signal sample rate for traces (PROVIDE_TRACE_SAMPLE_RATE).
    /// Combined with sampling.traces_rate via min() in apply_policies.
    pub sample_rate: f64,
    pub otlp_headers: HashMap<String, String>,
    /// OTLP endpoint URL for traces export. Falls back to the shared
    /// `OTEL_EXPORTER_OTLP_ENDPOINT` when `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`
    /// is unset.
    pub otlp_endpoint: Option<String>,
    /// OTLP transport protocol for traces. See `LoggingConfig::otlp_protocol`.
    pub otlp_protocol: String,
}

impl Default for TracingConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            sample_rate: 1.0,
            otlp_headers: HashMap::new(),
            otlp_endpoint: None,
            otlp_protocol: String::new(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct MetricsConfig {
    pub enabled: bool,
    pub otlp_headers: HashMap<String, String>,
    /// OTLP endpoint URL for metrics export. Falls back to the shared
    /// `OTEL_EXPORTER_OTLP_ENDPOINT` when `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT`
    /// is unset.
    pub otlp_endpoint: Option<String>,
    /// OTLP transport protocol for metrics. See `LoggingConfig::otlp_protocol`.
    pub otlp_protocol: String,
}

impl Default for MetricsConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            otlp_headers: HashMap::new(),
            otlp_endpoint: None,
            otlp_protocol: String::new(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct EventSchemaConfig {
    pub strict_event_name: bool,
    pub required_keys: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct SamplingConfig {
    pub logs_rate: f64,
    pub traces_rate: f64,
    pub metrics_rate: f64,
}

impl Default for SamplingConfig {
    fn default() -> Self {
        Self {
            logs_rate: 1.0,
            traces_rate: 1.0,
            metrics_rate: 1.0,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct BackpressureConfig {
    pub logs_maxsize: usize,
    pub traces_maxsize: usize,
    pub metrics_maxsize: usize,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ExporterPolicyConfig {
    pub logs_retries: usize,
    pub traces_retries: usize,
    pub metrics_retries: usize,
    pub logs_backoff_seconds: f64,
    pub traces_backoff_seconds: f64,
    pub metrics_backoff_seconds: f64,
    pub logs_timeout_seconds: f64,
    pub traces_timeout_seconds: f64,
    pub metrics_timeout_seconds: f64,
    pub logs_fail_open: bool,
    pub traces_fail_open: bool,
    pub metrics_fail_open: bool,
}

impl Default for ExporterPolicyConfig {
    fn default() -> Self {
        Self {
            logs_retries: 0,
            traces_retries: 0,
            metrics_retries: 0,
            logs_backoff_seconds: 0.0,
            traces_backoff_seconds: 0.0,
            metrics_backoff_seconds: 0.0,
            logs_timeout_seconds: 10.0,
            traces_timeout_seconds: 10.0,
            metrics_timeout_seconds: 10.0,
            logs_fail_open: true,
            traces_fail_open: true,
            metrics_fail_open: true,
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct SLOConfig {
    pub enable_red_metrics: bool,
    pub enable_use_metrics: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SecurityConfig {
    pub max_attr_value_length: usize,
    pub max_attr_count: usize,
}

impl Default for SecurityConfig {
    fn default() -> Self {
        Self {
            max_attr_value_length: 1024,
            max_attr_count: 64,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TelemetryConfig {
    pub service_name: String,
    pub environment: String,
    pub version: String,
    pub strict_schema: bool,
    pub pii_max_depth: usize,
    pub logging: LoggingConfig,
    pub tracing: TracingConfig,
    pub metrics: MetricsConfig,
    pub event_schema: EventSchemaConfig,
    pub sampling: SamplingConfig,
    pub backpressure: BackpressureConfig,
    pub exporter: ExporterPolicyConfig,
    pub slo: SLOConfig,
    pub security: SecurityConfig,
}

impl Default for TelemetryConfig {
    fn default() -> Self {
        Self {
            service_name: "provide-service".to_string(),
            environment: "dev".to_string(),
            version: "0.0.0".to_string(),
            strict_schema: false,
            pii_max_depth: 8,
            logging: LoggingConfig::default(),
            tracing: TracingConfig::default(),
            metrics: MetricsConfig::default(),
            event_schema: EventSchemaConfig::default(),
            sampling: SamplingConfig::default(),
            backpressure: BackpressureConfig::default(),
            exporter: ExporterPolicyConfig::default(),
            slo: SLOConfig::default(),
            security: SecurityConfig::default(),
        }
    }
}

impl TelemetryConfig {
    pub fn from_env() -> Result<Self, ConfigurationError> {
        let env_map = env::vars().collect::<HashMap<_, _>>();
        Self::from_map(&env_map)
    }

    pub fn from_map(env: &HashMap<String, String>) -> Result<Self, ConfigurationError> {
        let shared_headers = parse_otlp_headers(env_value(env, &["OTEL_EXPORTER_OTLP_HEADERS"]))?
            .unwrap_or_default();
        let shared_endpoint = env_value(env, &["OTEL_EXPORTER_OTLP_ENDPOINT"]);
        let shared_protocol = env_value(env, &["OTEL_EXPORTER_OTLP_PROTOCOL"]).unwrap_or("");
        // Per the OTLP/HTTP spec, when falling back to the shared endpoint
        // the per-signal path must be appended (/v1/traces, /v1/metrics,
        // /v1/logs). Signal-specific endpoint env vars are used verbatim.
        let with_signal_path = |signal_path: &str| -> Option<String> {
            shared_endpoint.map(|base| format!("{}/{}", base.trim_end_matches('/'), signal_path))
        };

        Ok(Self {
            service_name: env_value(env, &["PROVIDE_TELEMETRY_SERVICE_NAME"])
                .unwrap_or("provide-service")
                .to_string(),
            environment: env_value(env, &["PROVIDE_TELEMETRY_ENV", "PROVIDE_ENV"])
                .unwrap_or("dev")
                .to_string(),
            version: env_value(env, &["PROVIDE_TELEMETRY_VERSION", "PROVIDE_VERSION"])
                .unwrap_or("0.0.0")
                .to_string(),
            strict_schema: parse_bool(
                env_value(env, &["PROVIDE_TELEMETRY_STRICT_SCHEMA"]),
                false,
                "PROVIDE_TELEMETRY_STRICT_SCHEMA",
            )?,
            pii_max_depth: parse_usize(
                env_value(env, &["PROVIDE_LOG_PII_MAX_DEPTH"]),
                8,
                "PROVIDE_LOG_PII_MAX_DEPTH",
            )?,
            logging: LoggingConfig {
                level: env_value(env, &["PROVIDE_LOG_LEVEL"])
                    .unwrap_or("INFO")
                    .to_string(),
                fmt: env_value(env, &["PROVIDE_LOG_FORMAT"])
                    .unwrap_or("console")
                    .to_string(),
                include_timestamp: parse_bool(
                    env_value(env, &["PROVIDE_LOG_INCLUDE_TIMESTAMP"]),
                    true,
                    "PROVIDE_LOG_INCLUDE_TIMESTAMP",
                )?,
                otlp_headers: parse_otlp_headers(env_value(
                    env,
                    &["OTEL_EXPORTER_OTLP_LOGS_HEADERS"],
                ))?
                .unwrap_or_else(|| shared_headers.clone()),
                otlp_endpoint: env_value(env, &["OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"])
                    .or(shared_endpoint)
                    .map(str::to_string),
                otlp_protocol: env_value(env, &["OTEL_EXPORTER_OTLP_LOGS_PROTOCOL"])
                    .unwrap_or(shared_protocol)
                    .to_string(),
            },
            tracing: TracingConfig {
                enabled: parse_bool(
                    env_value(env, &["PROVIDE_TRACE_ENABLED"]),
                    true,
                    "PROVIDE_TRACE_ENABLED",
                )?,
                sample_rate: parse_rate(
                    env_value(env, &["PROVIDE_TRACE_SAMPLE_RATE"]),
                    1.0,
                    "PROVIDE_TRACE_SAMPLE_RATE",
                )?,
                otlp_headers: parse_otlp_headers(env_value(
                    env,
                    &["OTEL_EXPORTER_OTLP_TRACES_HEADERS"],
                ))?
                .unwrap_or_else(|| shared_headers.clone()),
                otlp_endpoint: env_value(env, &["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"])
                    .or(shared_endpoint)
                    .map(str::to_string),
                otlp_protocol: env_value(env, &["OTEL_EXPORTER_OTLP_TRACES_PROTOCOL"])
                    .unwrap_or(shared_protocol)
                    .to_string(),
            },
            metrics: MetricsConfig {
                enabled: parse_bool(
                    env_value(env, &["PROVIDE_METRICS_ENABLED"]),
                    true,
                    "PROVIDE_METRICS_ENABLED",
                )?,
                otlp_headers: parse_otlp_headers(env_value(
                    env,
                    &["OTEL_EXPORTER_OTLP_METRICS_HEADERS"],
                ))?
                .unwrap_or(shared_headers),
                otlp_endpoint: env_value(env, &["OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"])
                    .or(shared_endpoint)
                    .map(str::to_string),
                otlp_protocol: env_value(env, &["OTEL_EXPORTER_OTLP_METRICS_PROTOCOL"])
                    .unwrap_or(shared_protocol)
                    .to_string(),
            },
            event_schema: EventSchemaConfig {
                strict_event_name: parse_bool(
                    env_value(env, &["PROVIDE_TELEMETRY_STRICT_EVENT_NAME"]),
                    false,
                    "PROVIDE_TELEMETRY_STRICT_EVENT_NAME",
                )?,
                required_keys: env_value(env, &["PROVIDE_TELEMETRY_REQUIRED_KEYS"])
                    .unwrap_or("")
                    .split(',')
                    .map(str::trim)
                    .filter(|value| !value.is_empty())
                    .map(str::to_string)
                    .collect(),
            },
            sampling: SamplingConfig {
                logs_rate: parse_rate(
                    env_value(env, &["PROVIDE_SAMPLING_LOGS_RATE"]),
                    1.0,
                    "PROVIDE_SAMPLING_LOGS_RATE",
                )?,
                traces_rate: parse_rate(
                    env_value(env, &["PROVIDE_SAMPLING_TRACES_RATE"]),
                    1.0,
                    "PROVIDE_SAMPLING_TRACES_RATE",
                )?,
                metrics_rate: parse_rate(
                    env_value(env, &["PROVIDE_SAMPLING_METRICS_RATE"]),
                    1.0,
                    "PROVIDE_SAMPLING_METRICS_RATE",
                )?,
            },
            backpressure: BackpressureConfig {
                logs_maxsize: parse_usize(
                    env_value(env, &["PROVIDE_BACKPRESSURE_LOGS_MAXSIZE"]),
                    0,
                    "PROVIDE_BACKPRESSURE_LOGS_MAXSIZE",
                )?,
                traces_maxsize: parse_usize(
                    env_value(env, &["PROVIDE_BACKPRESSURE_TRACES_MAXSIZE"]),
                    0,
                    "PROVIDE_BACKPRESSURE_TRACES_MAXSIZE",
                )?,
                metrics_maxsize: parse_usize(
                    env_value(env, &["PROVIDE_BACKPRESSURE_METRICS_MAXSIZE"]),
                    0,
                    "PROVIDE_BACKPRESSURE_METRICS_MAXSIZE",
                )?,
            },
            exporter: ExporterPolicyConfig {
                logs_retries: parse_usize(
                    env_value(env, &["PROVIDE_EXPORTER_LOGS_RETRIES"]),
                    0,
                    "PROVIDE_EXPORTER_LOGS_RETRIES",
                )?,
                traces_retries: parse_usize(
                    env_value(env, &["PROVIDE_EXPORTER_TRACES_RETRIES"]),
                    0,
                    "PROVIDE_EXPORTER_TRACES_RETRIES",
                )?,
                metrics_retries: parse_usize(
                    env_value(env, &["PROVIDE_EXPORTER_METRICS_RETRIES"]),
                    0,
                    "PROVIDE_EXPORTER_METRICS_RETRIES",
                )?,
                logs_backoff_seconds: parse_non_negative_float(
                    env_value(env, &["PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS"]),
                    0.0,
                    "PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS",
                )?,
                traces_backoff_seconds: parse_non_negative_float(
                    env_value(env, &["PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS"]),
                    0.0,
                    "PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS",
                )?,
                metrics_backoff_seconds: parse_non_negative_float(
                    env_value(env, &["PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS"]),
                    0.0,
                    "PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS",
                )?,
                logs_timeout_seconds: parse_non_negative_float(
                    env_value(env, &["PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS"]),
                    10.0,
                    "PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS",
                )?,
                traces_timeout_seconds: parse_non_negative_float(
                    env_value(env, &["PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS"]),
                    10.0,
                    "PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS",
                )?,
                metrics_timeout_seconds: parse_non_negative_float(
                    env_value(env, &["PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS"]),
                    10.0,
                    "PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS",
                )?,
                logs_fail_open: parse_bool(
                    env_value(env, &["PROVIDE_EXPORTER_LOGS_FAIL_OPEN"]),
                    true,
                    "PROVIDE_EXPORTER_LOGS_FAIL_OPEN",
                )?,
                traces_fail_open: parse_bool(
                    env_value(env, &["PROVIDE_EXPORTER_TRACES_FAIL_OPEN"]),
                    true,
                    "PROVIDE_EXPORTER_TRACES_FAIL_OPEN",
                )?,
                metrics_fail_open: parse_bool(
                    env_value(env, &["PROVIDE_EXPORTER_METRICS_FAIL_OPEN"]),
                    true,
                    "PROVIDE_EXPORTER_METRICS_FAIL_OPEN",
                )?,
            },
            slo: SLOConfig {
                enable_red_metrics: parse_bool(
                    env_value(env, &["PROVIDE_SLO_ENABLE_RED_METRICS"]),
                    false,
                    "PROVIDE_SLO_ENABLE_RED_METRICS",
                )?,
                enable_use_metrics: parse_bool(
                    env_value(env, &["PROVIDE_SLO_ENABLE_USE_METRICS"]),
                    false,
                    "PROVIDE_SLO_ENABLE_USE_METRICS",
                )?,
            },
            security: SecurityConfig {
                max_attr_value_length: parse_usize(
                    env_value(env, &["PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH"]),
                    1024,
                    "PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH",
                )?,
                max_attr_count: parse_usize(
                    env_value(env, &["PROVIDE_SECURITY_MAX_ATTR_COUNT"]),
                    64,
                    "PROVIDE_SECURITY_MAX_ATTR_COUNT",
                )?,
            },
        })
    }
}
