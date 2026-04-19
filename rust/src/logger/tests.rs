// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

//! Tests for module-level logger helpers. Split out of `logger/mod.rs` so the
//! parent stays under the 500-LOC ceiling.

use super::*;
use std::collections::HashMap;

fn cfg_with_module_level(module: &str, level: &str) -> crate::config::LoggingConfig {
    let mut module_levels = HashMap::new();
    module_levels.insert(module.to_string(), level.to_string());
    crate::config::LoggingConfig {
        level: "INFO".to_string(),
        module_levels,
        ..crate::config::LoggingConfig::default()
    }
}

// ── Issue #2: dot-hierarchy prefix matching ───────────────────────────────

#[test]
fn effective_level_does_not_match_partial_string() {
    // "foobar" must NOT match prefix "foo" — no dot separator between them
    let cfg = cfg_with_module_level("foo", "DEBUG");
    // INFO = 2, so global threshold applies
    assert_eq!(
        effective_level_threshold("foobar", &cfg),
        2,
        "foobar must not match prefix foo (no dot separator)"
    );
}

#[test]
fn effective_level_matches_dot_separated_child() {
    // "foo.bar" starts with "foo." → should pick up DEBUG override
    let cfg = cfg_with_module_level("foo", "DEBUG");
    assert_eq!(
        effective_level_threshold("foo.bar", &cfg),
        1,
        "foo.bar must match prefix foo via dot separator"
    );
}

#[test]
fn effective_level_matches_exact_module_name() {
    // "foo" == "foo" → exact match → DEBUG override applies
    let cfg = cfg_with_module_level("foo", "DEBUG");
    assert_eq!(
        effective_level_threshold("foo", &cfg),
        1,
        "exact name must match"
    );
}

#[test]
fn effective_level_empty_prefix_matches_everything() {
    // empty prefix is a catch-all
    let cfg = cfg_with_module_level("", "DEBUG");
    assert_eq!(
        effective_level_threshold("anything.at.all", &cfg),
        1,
        "empty prefix must match any target"
    );
}

#[test]
fn effective_level_longest_prefix_wins() {
    let mut module_levels = HashMap::new();
    module_levels.insert("foo".to_string(), "WARN".to_string());
    module_levels.insert("foo.bar".to_string(), "DEBUG".to_string());
    let cfg = crate::config::LoggingConfig {
        level: "INFO".to_string(),
        module_levels,
        ..crate::config::LoggingConfig::default()
    };
    // "foo.bar.baz" matches both "foo" and "foo.bar"; "foo.bar" is longer → DEBUG wins
    assert_eq!(
        effective_level_threshold("foo.bar.baz", &cfg),
        1,
        "longer prefix must win over shorter"
    );
}
