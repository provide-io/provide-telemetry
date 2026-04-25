// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Pretty ANSI log renderer for CLI / terminal output.
//!
//! Cross-language parity with:
//!  * Python: `src/provide/telemetry/logger/pretty.py`
//!  * Go:     `go/logger_pretty.go`
//!
//! Line layout (matches Python `PrettyRenderer`):
//!
//! ```text
//! <dim timestamp> [<level-colored>] <logger_name> <message> key=value ...
//! ```
//!
//! Colors activate only when the sink is a TTY. Callers use
//! `format_pretty_line` / `emit_if_pretty`; tests can target
//! `format_pretty_line_with_colors` to force the color flag.

use super::LogEvent;
use crate::config::LoggingConfig;

// ---------------------------------------------------------------------------
// ANSI constants (inlined — stdlib-only, no new crate dependency)
// ---------------------------------------------------------------------------

pub(super) const ANSI_RESET: &str = "\x1b[0m";
pub(super) const ANSI_DIM: &str = "\x1b[2m";
pub(super) const ANSI_BOLD: &str = "\x1b[1m";

pub(super) const ANSI_RED: &str = "\x1b[31m";
pub(super) const ANSI_GREEN: &str = "\x1b[32m";
pub(super) const ANSI_YELLOW: &str = "\x1b[33m";
pub(super) const ANSI_BLUE: &str = "\x1b[34m";
pub(super) const ANSI_CYAN: &str = "\x1b[36m";
pub(super) const ANSI_WHITE: &str = "\x1b[37m";
pub(super) const ANSI_BOLD_RED: &str = "\x1b[31;1m";

/// Width used to pad level names so columns align. "critical" = 8 chars,
/// padded to 9 to match Python/Go.
pub(super) const LEVEL_PAD: usize = 9;

// ---------------------------------------------------------------------------
// Level + named-color resolution
// ---------------------------------------------------------------------------

/// Map a canonical lowercased level name to its ANSI color escape.
/// Unknown levels yield an empty string (no color).
pub(super) fn level_color(level_lower: &str) -> &'static str {
    match level_lower {
        "critical" | "fatal" => ANSI_BOLD_RED,
        "error" => ANSI_RED,
        "warning" | "warn" => ANSI_YELLOW,
        "info" => ANSI_GREEN,
        "debug" => ANSI_BLUE,
        "trace" => ANSI_CYAN,
        _ => "",
    }
}

/// Map a friendly color name (matching Python `NAMED_COLORS`) to an ANSI
/// escape sequence. Unknown / empty names resolve to "" (no color).
pub(super) fn resolve_named_color(name: &str) -> &'static str {
    match name.trim().to_ascii_lowercase().as_str() {
        "dim" => ANSI_DIM,
        "bold" => ANSI_BOLD,
        "red" => ANSI_RED,
        "green" => ANSI_GREEN,
        "yellow" => ANSI_YELLOW,
        "blue" => ANSI_BLUE,
        "cyan" => ANSI_CYAN,
        "white" => ANSI_WHITE,
        "" | "none" => "",
        _ => "",
    }
}

// ---------------------------------------------------------------------------
// Rendering helpers
// ---------------------------------------------------------------------------

fn wrap(s: &str, color: &str, colors: bool) -> String {
    if colors && !color.is_empty() {
        format!("{color}{s}{ANSI_RESET}")
    } else {
        s.to_string()
    }
}

fn format_level(level: &str, colors: bool) -> String {
    let lower = level.to_ascii_lowercase();
    let pad_width = LEVEL_PAD.saturating_sub(lower.chars().count());
    let padded = format!("{lower}{}", " ".repeat(pad_width));
    if colors {
        let color = level_color(&lower);
        if !color.is_empty() {
            return format!("[{color}{padded}{ANSI_RESET}]");
        }
    }
    format!("[{padded}]")
}

/// Render a JSON `Value` for display — strings are quoted (repr-style),
/// everything else uses its canonical JSON serialization so booleans,
/// numbers, arrays, and objects stay readable.
fn format_value(v: &serde_json::Value) -> String {
    match v {
        serde_json::Value::String(s) => format!("{s:?}"),
        other => other.to_string(),
    }
}

/// Render a complete pretty log line for the given `event` with the
/// explicit `colors` flag — primarily used by tests.
pub(super) fn format_pretty_line_with_colors(
    event: &LogEvent,
    cfg: &LoggingConfig,
    colors: bool,
) -> String {
    let mut parts: Vec<String> = Vec::new();

    if cfg.include_timestamp {
        let ts = super::emit::now_iso8601();
        parts.push(wrap(&ts, ANSI_DIM, colors));
    }

    parts.push(format_level(&event.level, colors));

    if !event.target.is_empty() {
        parts.push(event.target.clone());
    }

    parts.push(event.message.clone());

    let key_color = resolve_named_color(&cfg.pretty_key_color);
    let value_color = resolve_named_color(&cfg.pretty_value_color);

    // `BTreeMap` iteration is sorted — keeps output deterministic and matches
    // the Python renderer which sorts keys.
    for (k, v) in &event.context {
        let kp = wrap(k, key_color, colors);
        let vs = format_value(v);
        let vp = wrap(&vs, value_color, colors);
        parts.push(format!("{kp}={vp}"));
    }

    if let Some(trace_id) = &event.trace_id {
        let kp = wrap("trace_id", key_color, colors);
        let vs = format!("{trace_id:?}");
        let vp = wrap(&vs, value_color, colors);
        parts.push(format!("{kp}={vp}"));
    }
    if let Some(span_id) = &event.span_id {
        let kp = wrap("span_id", key_color, colors);
        let vs = format!("{span_id:?}");
        let vp = wrap(&vs, value_color, colors);
        parts.push(format!("{kp}={vp}"));
    }

    parts.join(" ")
}

/// Render a pretty log line, auto-detecting whether stderr is a TTY.
/// Piped / redirected output gets plain text (no ANSI escapes).
pub(super) fn format_pretty_line(event: &LogEvent, cfg: &LoggingConfig) -> String {
    format_pretty_line_with_colors(event, cfg, stderr_is_tty())
}

/// stdlib-only TTY detection — available since Rust 1.70.
fn stderr_is_tty() -> bool {
    use std::io::IsTerminal;
    std::io::stderr().is_terminal()
}

#[cfg(test)]
#[path = "pretty_tests.rs"]
mod tests;
