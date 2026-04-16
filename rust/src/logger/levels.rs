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

/// Resolve the effective level threshold for a given target (logger name).
/// Per-module overrides win via longest-prefix match; falls back to the
/// global default level.
pub(crate) fn effective_level_threshold(target: &str, config: &LoggingConfig) -> u8 {
    let mut best_match: Option<usize> = None;
    let mut threshold = level_order(&config.level);
    for (prefix, lvl) in &config.module_levels {
        let matches = prefix.is_empty()
            || target == prefix.as_str()
            || target.starts_with(&format!("{prefix}."));
        if matches {
            let plen = prefix.len();
            if best_match.map_or(true, |best| plen > best) {
                best_match = Some(plen);
                threshold = level_order(lvl);
            }
        }
    }
    threshold
}
