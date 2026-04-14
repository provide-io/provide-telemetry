// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::HashMap;
use std::env;

use percent_encoding::percent_decode_str;
use serde::{Deserialize, Serialize};

use crate::errors::ConfigurationError;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Default)]
pub struct RuntimeOverrides {
    pub sampling: Option<SamplingConfig>,
    pub backpressure: Option<BackpressureConfig>,
    pub exporter: Option<ExporterPolicyConfig>,
    pub security: Option<SecurityConfig>,
    pub slo: Option<SLOConfig>,
    pub pii_max_depth: Option<usize>,
    pub strict_schema: Option<bool>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct LoggingConfig {
    pub level: String,
    pub fmt: String,
    /// Whether to include an ISO 8601 timestamp in JSON log output.
    /// Controlled by `PROVIDE_LOG_INCLUDE_TIMESTAMP` (default: true).
    pub include_timestamp: bool,
    pub otlp_headers: HashMap<String, String>,
}

impl Default for LoggingConfig {
    fn default() -> Self {
        Self {
            level: "INFO".to_string(),
            fmt: "console".to_string(),
            include_timestamp: true,
            otlp_headers: HashMap::new(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct TracingConfig {
    pub enabled: bool,
    pub otlp_headers: HashMap<String, String>,
}

impl Default for TracingConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            otlp_headers: HashMap::new(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct MetricsConfig {
    pub enabled: bool,
    pub otlp_headers: HashMap<String, String>,
}

impl Default for MetricsConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            otlp_headers: HashMap::new(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct SchemaConfig {
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
    pub event_schema: SchemaConfig,
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
            event_schema: SchemaConfig::default(),
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
            },
            tracing: TracingConfig {
                enabled: parse_bool(
                    env_value(env, &["PROVIDE_TRACE_ENABLED"]),
                    true,
                    "PROVIDE_TRACE_ENABLED",
                )?,
                otlp_headers: parse_otlp_headers(env_value(
                    env,
                    &["OTEL_EXPORTER_OTLP_TRACES_HEADERS"],
                ))?
                .unwrap_or_else(|| shared_headers.clone()),
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
            },
            event_schema: SchemaConfig::default(),
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

pub fn redact_config(cfg: &TelemetryConfig) -> TelemetryConfig {
    fn mask(headers: &HashMap<String, String>) -> HashMap<String, String> {
        headers
            .keys()
            .map(|k| (k.clone(), "***REDACTED***".to_string()))
            .collect()
    }
    let mut out = cfg.clone();
    if !out.logging.otlp_headers.is_empty() {
        out.logging.otlp_headers = mask(&cfg.logging.otlp_headers);
    }
    if !out.tracing.otlp_headers.is_empty() {
        out.tracing.otlp_headers = mask(&cfg.tracing.otlp_headers);
    }
    if !out.metrics.otlp_headers.is_empty() {
        out.metrics.otlp_headers = mask(&cfg.metrics.otlp_headers);
    }
    out
}

fn env_value<'a>(env: &'a HashMap<String, String>, keys: &[&str]) -> Option<&'a str> {
    keys.iter()
        .find_map(|key| env.get(*key).map(String::as_str))
}

fn parse_bool(raw: Option<&str>, default: bool, field: &str) -> Result<bool, ConfigurationError> {
    match raw.map(str::trim) {
        None | Some("") => Ok(default),
        Some(value)
            if matches!(
                value.to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "on"
            ) =>
        {
            Ok(true)
        }
        Some(value)
            if matches!(
                value.to_ascii_lowercase().as_str(),
                "0" | "false" | "no" | "off"
            ) =>
        {
            Ok(false)
        }
        Some(value) => Err(ConfigurationError::new(format!(
            "invalid boolean for {field}: {value:?} (expected one of: 1,true,yes,on,0,false,no,off)"
        ))),
    }
}

fn parse_usize(
    raw: Option<&str>,
    default: usize,
    field: &str,
) -> Result<usize, ConfigurationError> {
    match raw.map(str::trim) {
        None | Some("") => Ok(default),
        Some(value) => value.parse::<usize>().map_err(|_| {
            ConfigurationError::new(format!("invalid integer for {field}: {value:?}"))
        }),
    }
}

fn parse_non_negative_float(
    raw: Option<&str>,
    default: f64,
    field: &str,
) -> Result<f64, ConfigurationError> {
    match raw.map(str::trim) {
        None | Some("") => Ok(default),
        Some(value) => {
            let parsed = value.parse::<f64>().map_err(|_| {
                ConfigurationError::new(format!("invalid float for {field}: {value:?}"))
            })?;
            if !parsed.is_finite() || parsed < 0.0 {
                return Err(ConfigurationError::new(format!(
                    "{field} must be >= 0, got {parsed}"
                )));
            }
            Ok(parsed)
        }
    }
}

fn parse_rate(raw: Option<&str>, default: f64, field: &str) -> Result<f64, ConfigurationError> {
    let parsed = parse_non_negative_float(raw, default, field)?;
    if !(0.0..=1.0).contains(&parsed) {
        return Err(ConfigurationError::new(format!(
            "{field} must be in [0, 1], got {parsed}"
        )));
    }
    Ok(parsed)
}

fn parse_otlp_headers(
    raw: Option<&str>,
) -> Result<Option<HashMap<String, String>>, ConfigurationError> {
    let Some(raw) = raw else {
        return Ok(None);
    };
    if raw.trim().is_empty() {
        return Ok(Some(HashMap::new()));
    }

    let mut headers = HashMap::new();
    for pair in raw.split(',') {
        let Some((key, value)) = pair.split_once('=') else {
            continue;
        };
        let Ok(key) = decode_header_component(key.trim()) else {
            continue;
        };
        if key.is_empty() {
            continue;
        }
        let Ok(value) = decode_header_component(value.trim()) else {
            continue;
        };
        headers.insert(key, value);
    }
    Ok(Some(headers))
}

fn decode_header_component(raw: &str) -> Result<String, ConfigurationError> {
    if has_invalid_percent_encoding(raw) {
        return Err(ConfigurationError::new(format!(
            "invalid OTLP header encoding: {raw:?}"
        )));
    }
    Ok(percent_decode_str(raw).decode_utf8_lossy().into_owned())
}

fn has_invalid_percent_encoding(raw: &str) -> bool {
    let bytes = raw.as_bytes();
    let mut idx = 0;
    while idx < bytes.len() {
        if bytes[idx] == b'%' {
            if idx + 2 >= bytes.len()
                || !bytes[idx + 1].is_ascii_hexdigit()
                || !bytes[idx + 2].is_ascii_hexdigit()
            {
                return true;
            }
            idx += 3;
            continue;
        }
        idx += 1;
    }
    false
}
