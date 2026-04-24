// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Env-var parsing helpers for `TelemetryConfig::from_map`.
//!
//! Split out from `config/mod.rs` to keep each file under the 500-LOC cap.

use std::collections::HashMap;

use percent_encoding::percent_decode_str;

use crate::errors::ConfigurationError;

pub(super) fn env_value<'a>(env: &'a HashMap<String, String>, keys: &[&str]) -> Option<&'a str> {
    for key in keys {
        if let Some(value) = env.get(*key) {
            return Some(value.as_str());
        }
    }
    None
}

pub(super) fn nonempty_env_value<'a>(
    env: &'a HashMap<String, String>,
    keys: &[&str],
) -> Option<&'a str> {
    let value = env_value(env, keys)?;
    if value.trim().is_empty() {
        return None;
    }
    Some(value)
}

pub(super) fn parse_bool(
    raw: Option<&str>,
    default: bool,
    field: &str,
) -> Result<bool, ConfigurationError> {
    match raw.map(str::trim) {
        None | Some("") => Ok(default),
        Some(value) => {
            let normalized = value.to_ascii_lowercase();
            match normalized.as_str() {
                "1" | "true" | "yes" | "on" => Ok(true),
                "0" | "false" | "no" | "off" => Ok(false),
                _ => Err(ConfigurationError::new(format!(
                    "invalid boolean for {field}: {value:?} (expected one of: 1,true,yes,on,0,false,no,off)"
                ))),
            }
        }
    }
}

pub(super) fn parse_usize(
    raw: Option<&str>,
    default: usize,
    field: &str,
) -> Result<usize, ConfigurationError> {
    match raw.map(str::trim) {
        None | Some("") => Ok(default),
        Some(value) => match value.parse::<usize>() {
            Ok(parsed) => Ok(parsed),
            Err(_) => Err(ConfigurationError::new(format!(
                "invalid integer for {field}: {value:?}"
            ))),
        },
    }
}

pub(super) fn parse_non_negative_float(
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

pub(super) fn parse_rate(
    raw: Option<&str>,
    default: f64,
    field: &str,
) -> Result<f64, ConfigurationError> {
    let parsed = parse_non_negative_float(raw, default, field)?;
    if parsed > 1.0 {
        return Err(ConfigurationError::new(format!(
            "{field} must be in [0, 1], got {parsed}"
        )));
    }
    Ok(parsed)
}

pub(super) fn parse_otlp_headers(raw: Option<&str>) -> Option<HashMap<String, String>> {
    let raw = raw?;
    if raw.trim().is_empty() {
        return Some(HashMap::new());
    }

    let mut headers = HashMap::new();
    for pair in raw.split(',') {
        let (key, value) = match pair.split_once('=') {
            Some(key_value) => key_value,
            None => continue,
        };

        let key = match decode_header_component(key.trim()) {
            Some(key) => key,
            None => continue,
        };
        if key.is_empty() {
            continue;
        }

        let value = match decode_header_component(value.trim()) {
            Some(value) => value,
            None => continue,
        };
        headers.insert(key, value);
    }
    Some(headers)
}

fn decode_header_component(raw: &str) -> Option<String> {
    if has_invalid_percent_encoding(raw) {
        return None;
    }
    let decoded = percent_decode_str(raw).decode_utf8_lossy();
    Some(decoded.into_owned())
}

/// Parse `PROVIDE_LOG_MODULE_LEVELS` — comma-separated `module=LEVEL` pairs.
/// Example: `"provide.server=DEBUG,asyncio=WARNING"`.
/// Unknown level strings emit a stderr warning and default to INFO at runtime.
pub(super) fn parse_module_levels(raw: &str) -> HashMap<String, String> {
    const VALID_LEVELS: &[&str] = &[
        "TRACE", "DEBUG", "INFO", "WARN", "WARNING", "ERROR", "CRITICAL", "FATAL",
    ];
    let mut map = HashMap::new();
    for pair in raw.split(',') {
        let pair = pair.trim();
        if pair.is_empty() {
            continue;
        }

        let (module, level) = match pair.split_once('=') {
            Some(module_level) => module_level,
            None => continue,
        };
        let module = module.trim().to_string();
        let level = level.trim().to_uppercase();
        if module.is_empty() || level.is_empty() {
            continue;
        }
        if !VALID_LEVELS.contains(&level.as_str()) {
            eprintln!(
                "provide_telemetry: unknown log level {level:?} for module {module:?} \
                 in PROVIDE_LOG_MODULE_LEVELS; will default to INFO at runtime"
            );
        }
        map.insert(module, level);
    }
    map
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

#[cfg(test)]
#[path = "parse_tests.rs"]
mod tests;
