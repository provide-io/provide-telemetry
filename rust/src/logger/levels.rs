// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use crate::config::LoggingConfig;

/// The canonical severity ladder. The discriminant is the rank, so severities
/// compare directly with `<` and `>`.
///
/// WARNING and FATAL are deliberately absent: they are spellings resolved by
/// [`try_parse_level`], not members. Admitting an alias as a member is how Warn
/// and Warning both ended up on the public C# Logger surface.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum LogSeverity {
    Trace = 0,
    Debug = 1,
    Info = 2,
    Warn = 3,
    Error = 4,
    Critical = 5,
}

impl LogSeverity {
    /// Numeric rank, for threshold comparisons.
    #[must_use]
    pub fn order(self) -> u8 {
        self as u8
    }

    /// The canonical uppercase spelling, as it appears on the record.
    #[must_use]
    pub fn name(self) -> &'static str {
        match self {
            Self::Trace => "TRACE",
            Self::Debug => "DEBUG",
            Self::Info => "INFO",
            Self::Warn => "WARN",
            Self::Error => "ERROR",
            Self::Critical => "CRITICAL",
        }
    }
}

/// Resolve a level string, or `None` when it is not recognised.
///
/// Trims surrounding whitespace; comparison is case-insensitive. This is the
/// one place in the crate where a level string becomes a level. It previously
/// folded CRITICAL and FATAL onto ERROR, which made a CRITICAL threshold admit
/// ERROR records and left the ladder's top two levels indistinguishable.
#[must_use]
pub fn try_parse_level(level: &str) -> Option<LogSeverity> {
    match level.trim().to_ascii_uppercase().as_str() {
        "TRACE" => Some(LogSeverity::Trace),
        "DEBUG" => Some(LogSeverity::Debug),
        "INFO" => Some(LogSeverity::Info),
        "WARN" | "WARNING" => Some(LogSeverity::Warn),
        "ERROR" => Some(LogSeverity::Error),
        "CRITICAL" | "FATAL" => Some(LogSeverity::Critical),
        _ => None,
    }
}

/// Resolve a level string, substituting `fallback` when it is not recognised.
///
/// The fallback has no default: Rust has no default arguments, so every call
/// site states which severity an unrecognised token becomes.
#[must_use]
pub fn parse_level(level: &str, fallback: LogSeverity) -> LogSeverity {
    try_parse_level(level).unwrap_or(fallback)
}

/// Numeric rank of a level string, with unrecognised values ranking INFO.
#[must_use]
pub fn level_order(level: &str) -> u8 {
    parse_level(level, LogSeverity::Info).order()
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
