// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use crate::config::LoggingConfig;

/// Map level string to a numeric order for comparison.
/// CRITICAL/FATAL are aliases for ERROR (same severity).
pub(crate) fn level_order(level: &str) -> u8 {
    match level.to_ascii_uppercase().as_str() {
        "TRACE" => 0,
        "DEBUG" => 1,
        "INFO" => 2,
        "WARN" | "WARNING" => 3,
        "ERROR" | "CRITICAL" | "FATAL" => 4,
        _ => 2, // default to INFO
    }
}

fn match_len(target: &str, prefix: &str) -> Option<usize> {
    if prefix.is_empty() || target == prefix {
        return Some(prefix.len());
    }
    target
        .strip_prefix(prefix)
        .filter(|suffix| suffix.starts_with('.'))
        .map(|_| prefix.len())
}

/// Resolve the effective level threshold for a given target (logger name).
/// Per-module overrides win via longest-prefix match; falls back to the
/// global default level.
pub(crate) fn effective_level_threshold(target: &str, config: &LoggingConfig) -> u8 {
    let default_threshold = level_order(&config.level);
    config
        .module_levels
        .iter()
        .filter_map(|(prefix, level)| match_len(target, prefix).map(|len| (len, level)))
        .max_by_key(|(len, _)| *len)
        .map_or(default_threshold, |(_, level)| level_order(level))
}

#[cfg(test)]
#[path = "levels_tests.rs"]
mod tests;
