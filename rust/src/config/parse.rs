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
    keys.iter()
        .find_map(|key| env.get(*key).map(String::as_str))
}

pub(super) fn parse_bool(
    raw: Option<&str>,
    default: bool,
    field: &str,
) -> Result<bool, ConfigurationError> {
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

pub(super) fn parse_usize(
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
    if !(0.0..=1.0).contains(&parsed) {
        return Err(ConfigurationError::new(format!(
            "{field} must be in [0, 1], got {parsed}"
        )));
    }
    Ok(parsed)
}

pub(super) fn parse_otlp_headers(
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
