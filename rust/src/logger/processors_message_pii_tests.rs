// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Cross-language regression: secrets embedded in the log message string
//! must be replaced with the redaction sentinel. Companion tests:
//!   * Python: tests/regression/test_message_pii_cross_language.py
//!   * Go:     go/logger_handlers_test.go (TestHandler_PIISanitization_MessageContent*)
//!   * TS:     typescript/tests/logger.pii-message.test.ts
//!
//! Rust originally only sanitized the context map, letting the message
//! pass through verbatim — same bug Go had. Mounted via `#[path]` from
//! `processors.rs` to keep that file under the 500-line LOC budget.

use super::super::LogEvent;
use super::sanitize_context;
use crate::pii::REDACTED_SENTINEL;
use crate::{register_secret_pattern, reset_secret_patterns_for_tests};
use regex::Regex;
use std::collections::BTreeMap;

fn make_event(message: &str) -> LogEvent {
    LogEvent {
        level: "INFO".to_string(),
        target: "test".to_string(),
        message: message.to_string(),
        context: BTreeMap::new(),
        trace_id: None,
        span_id: None,
        event_metadata: None,
    }
}

#[test]
fn sanitize_context_redacts_secret_in_message_string() {
    let mut event = make_event("token AKIAIOSFODNN7EXAMPLE leaked");
    sanitize_context(&mut event, 8);
    assert_eq!(
        event.message, REDACTED_SENTINEL,
        "message containing a known secret must be redacted"
    );
}

#[test]
fn sanitize_context_leaves_clean_message_unchanged() {
    let mut event = make_event("user login succeeded");
    sanitize_context(&mut event, 8);
    assert_eq!(
        event.message, "user login succeeded",
        "messages without secret patterns must pass through unchanged"
    );
}

#[test]
fn sanitize_context_redacts_custom_secret_pattern_in_message_string() {
    reset_secret_patterns_for_tests();
    register_secret_pattern(
        "internal_token",
        Regex::new(r"INTSECRET-[A-Z0-9]{12,}").expect("valid regex"),
    );
    let mut event = make_event("token INTSECRET-ABC123XYZ789 leaked");
    sanitize_context(&mut event, 8);
    assert_eq!(
        event.message, REDACTED_SENTINEL,
        "message containing a registered custom secret must be redacted"
    );
    reset_secret_patterns_for_tests();
}
