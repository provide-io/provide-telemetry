// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Parsing and validation for the Prometheus metrics settings.
//!
//! See `prometheus_metrics.config_rules` in `spec/telemetry-api.yaml`. Invalid
//! values are a [`ConfigurationError`], as for the crate's other validated keys,
//! whether they come from the environment or from a config built in code.

use serde::{Deserialize, Serialize};

use crate::errors::ConfigurationError;

pub(crate) const EXPORTER_OTLP: &str = "otlp";
pub(crate) const EXPORTER_PROMETHEUS: &str = "prometheus";
const EXPORTER_NONE: &str = "none";
const LISTEN_VALUES: [&str; 3] = ["false", "true", "auto"];
const DEFAULT_HOST: &str = "127.0.0.1";
const DEFAULT_PORT: u16 = 9464;
const DEFAULT_PATH: &str = "/metrics";
const DEFAULT_TRANSLATION: &str = "UnderscoreEscapingWithSuffixes";
/// Every value `PROVIDE_METRICS_PROMETHEUS_TRANSLATION` accepts.
pub(crate) const TRANSLATION_STRATEGIES: [&str; 4] = [
    "UnderscoreEscapingWithSuffixes",
    "UnderscoreEscapingWithoutSuffixes",
    "NoUTF8EscapingWithSuffixes",
    "NoTranslation",
];

/// Prometheus pull reader, handler and listener settings.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct PrometheusConfig {
    /// `false`, `true`, or `auto` (listen whenever `prometheus` is an exporter).
    pub listen: String,
    pub host: String,
    /// 0 asks the OS for a free port.
    pub port: u16,
    pub path: String,
    pub translation: String,
    pub scope_labels: bool,
    pub target_info: bool,
    /// Path to a Prometheus web config file; empty means plain HTTP, no auth.
    pub web_config: String,
}

impl Default for PrometheusConfig {
    fn default() -> Self {
        Self {
            listen: "false".to_string(),
            host: DEFAULT_HOST.to_string(),
            port: DEFAULT_PORT,
            path: DEFAULT_PATH.to_string(),
            translation: DEFAULT_TRANSLATION.to_string(),
            scope_labels: false,
            target_info: true,
            web_config: String::new(),
        }
    }
}

impl PrometheusConfig {
    pub(crate) fn validate(&self) -> Result<(), ConfigurationError> {
        validate_listen(&self.listen)?;
        validate_path(&self.path)?;
        validate_translation(&self.translation)
    }
}

pub(crate) fn default_exporters() -> Vec<String> {
    vec![EXPORTER_OTLP.to_string()]
}

/// Parse `OTEL_METRICS_EXPORTER`: entries split on commas, trimmed and
/// lowercased, empty ones dropped. Empty input means `otlp`; `none` alone means
/// no exporters and may not be combined with another.
pub(crate) fn parse_exporters(raw: Option<&str>) -> Result<Vec<String>, ConfigurationError> {
    let names: Vec<String> = raw
        .unwrap_or("")
        .split(',')
        .map(|part| part.trim().to_ascii_lowercase())
        .filter(|part| !part.is_empty())
        .collect();
    if let Some(unknown) = names
        .iter()
        .find(|name| ![EXPORTER_OTLP, EXPORTER_PROMETHEUS, EXPORTER_NONE].contains(&name.as_str()))
    {
        return Err(ConfigurationError::new(format!(
            "OTEL_METRICS_EXPORTER: unknown exporter {unknown:?}"
        )));
    }
    let has_none = names.iter().any(|name| name == EXPORTER_NONE);
    let exporters: Vec<String> = names
        .into_iter()
        .filter(|name| name != EXPORTER_NONE)
        .collect();
    if has_none {
        if !exporters.is_empty() {
            return Err(ConfigurationError::new(
                "OTEL_METRICS_EXPORTER: none cannot be combined with other exporters",
            ));
        }
        return Ok(exporters);
    }
    if exporters.is_empty() {
        return Ok(default_exporters());
    }
    Ok(exporters)
}

/// Reject an exporter list built in code with a name the env parser would refuse.
pub(crate) fn validate_exporters(exporters: &[String]) -> Result<(), ConfigurationError> {
    match exporters
        .iter()
        .find(|name| ![EXPORTER_OTLP, EXPORTER_PROMETHEUS].contains(&name.as_str()))
    {
        Some(unknown) => Err(ConfigurationError::new(format!(
            "metrics exporters: unknown {unknown:?}"
        ))),
        None => Ok(()),
    }
}

/// Parse `OTEL_EXPORTER_PROMETHEUS_PORT`: an integer in 0-65535.
pub(crate) fn parse_port(raw: Option<&str>) -> Result<u16, ConfigurationError> {
    let value = raw.unwrap_or("").trim();
    if value.is_empty() {
        return Ok(DEFAULT_PORT);
    }
    value.parse::<u16>().map_err(|_| {
        ConfigurationError::new(format!(
            "OTEL_EXPORTER_PROMETHEUS_PORT: want an integer in 0-65535, got {value:?}"
        ))
    })
}

fn validate_listen(listen: &str) -> Result<(), ConfigurationError> {
    if LISTEN_VALUES.contains(&listen) {
        return Ok(());
    }
    Err(ConfigurationError::new(format!(
        "PROVIDE_METRICS_PROMETHEUS_LISTEN: want false, true or auto, got {listen:?}"
    )))
}

fn validate_path(path: &str) -> Result<(), ConfigurationError> {
    if path.starts_with('/') && !path.contains('?') && !path.contains('#') {
        return Ok(());
    }
    Err(ConfigurationError::new(format!(
        "PROVIDE_METRICS_PROMETHEUS_PATH: want a path starting with / and no query or fragment, got {path:?}"
    )))
}

fn validate_translation(translation: &str) -> Result<(), ConfigurationError> {
    if TRANSLATION_STRATEGIES.contains(&translation) {
        return Ok(());
    }
    Err(ConfigurationError::new(format!(
        "PROVIDE_METRICS_PROMETHEUS_TRANSLATION: unknown strategy {translation:?}"
    )))
}

/// A trimmed string setting; empty or unset means the default.
pub(crate) fn env_str(raw: Option<&str>, default: &str) -> String {
    let value = raw.unwrap_or("").trim();
    if value.is_empty() {
        return default.to_string();
    }
    value.to_string()
}

/// Build the Prometheus settings from already-looked-up raw values, validating each.
pub(crate) struct RawPrometheus<'a> {
    pub listen: Option<&'a str>,
    pub host: Option<&'a str>,
    pub port: Option<&'a str>,
    pub path: Option<&'a str>,
    pub translation: Option<&'a str>,
    pub scope_labels: bool,
    pub target_info: bool,
    pub web_config: Option<&'a str>,
}

impl RawPrometheus<'_> {
    pub(crate) fn parse(self) -> Result<PrometheusConfig, ConfigurationError> {
        let config = PrometheusConfig {
            listen: env_str(self.listen, "false").to_ascii_lowercase(),
            host: env_str(self.host, DEFAULT_HOST),
            port: parse_port(self.port)?,
            path: env_str(self.path, DEFAULT_PATH),
            translation: env_str(self.translation, DEFAULT_TRANSLATION),
            scope_labels: self.scope_labels,
            target_info: self.target_info,
            web_config: env_str(self.web_config, ""),
        };
        config.validate()?;
        Ok(config)
    }
}

#[cfg(test)]
#[path = "prometheus_tests.rs"]
mod tests;
