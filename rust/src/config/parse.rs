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

/// Parse `PROVIDE_LOG_MODULE_LEVELS` — comma-separated `module=LEVEL` pairs.
/// Example: `"provide.server=DEBUG,asyncio=WARNING"`.
/// Unknown level strings emit a stderr warning and default to INFO at runtime.
pub(super) fn parse_module_levels(raw: &str) -> HashMap<String, String> {
    const VALID_LEVELS: &[&str] =
        &["TRACE", "DEBUG", "INFO", "WARN", "WARNING", "ERROR", "CRITICAL", "FATAL"];
    let mut map = HashMap::new();
    for pair in raw.split(',') {
        let pair = pair.trim();
        if pair.is_empty() {
            continue;
        }
        if let Some((module, level)) = pair.split_once('=') {
            let module = module.trim().to_string();
            let level = level.trim().to_uppercase();
            if !module.is_empty() && !level.is_empty() {
                if !VALID_LEVELS.contains(&level.as_str()) {
                    eprintln!(
                        "provide_telemetry: unknown log level {level:?} for module {module:?} \
                         in PROVIDE_LOG_MODULE_LEVELS; will default to INFO at runtime"
                    );
                }
                map.insert(module, level);
            }
        }
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
mod tests {
    use super::*;

    #[test]
    fn parse_module_levels_inserts_unknown_level_and_warns() {
        // Unknown level strings are still inserted (runtime defaults to INFO),
        // but a warning must be emitted to stderr. We verify the map entry is
        // present to ensure the warning path doesn't accidentally drop the entry.
        let map = parse_module_levels("foo=VERBOSE,bar=DEBUG");
        assert_eq!(
            map.get("foo").map(String::as_str),
            Some("VERBOSE"),
            "unknown level must still be inserted into the map"
        );
        assert_eq!(
            map.get("bar").map(String::as_str),
            Some("DEBUG"),
            "valid entry must not be affected by adjacent unknown entry"
        );
    }

    #[test]
    fn parse_module_levels_valid_levels_no_warning() {
        let map =
            parse_module_levels("a=TRACE,b=DEBUG,c=INFO,d=WARN,e=WARNING,f=ERROR,g=CRITICAL,h=FATAL");
        assert_eq!(map.len(), 8, "all valid levels must parse");
    }

    #[test]
    fn parse_module_levels_empty_input() {
        let map = parse_module_levels("");
        assert!(map.is_empty());
    }

    #[test]
    fn parse_module_levels_skips_empty_module_name() {
        let map = parse_module_levels("=DEBUG,pkg=INFO");
        assert!(!map.contains_key(""), "empty module name must be skipped");
        assert_eq!(map.get("pkg").map(String::as_str), Some("INFO"));
    }

    #[test]
    fn parse_module_levels_skips_empty_level() {
        let map = parse_module_levels("pkg=,other=DEBUG");
        assert!(!map.contains_key("pkg"), "empty level must be skipped");
        assert_eq!(map.get("other").map(String::as_str), Some("DEBUG"));
    }

    #[test]
    fn parse_module_levels_trims_whitespace() {
        let map = parse_module_levels("  pkg = DEBUG , other = INFO ");
        assert_eq!(map.get("pkg").map(String::as_str), Some("DEBUG"));
        assert_eq!(map.get("other").map(String::as_str), Some("INFO"));
    }
}
