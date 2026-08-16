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
use crate::testing::{acquire_test_state_lock, reset_telemetry_state};
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
    // Span-scoped since 2026-08-16: the credential token is replaced and the
    // words around it survive. What this pins is that the secret cannot reach
    // the log; blanking the whole message was the old mechanism, not the rule.
    assert!(
        !event.message.contains("AKIAIOSFODNN7EXAMPLE"),
        "secret survived redaction: {}",
        event.message
    );
    assert_eq!(
        event.message, "token *** leaked",
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
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    register_secret_pattern(
        "internal_token",
        Regex::new(r"INTSECRET-[A-Z0-9]{12,}").expect("valid regex"),
    );
    let mut event = make_event("token INTSECRET-ABC123XYZ789 leaked");
    sanitize_context(&mut event, 8);
    assert!(
        !event.message.contains("INTSECRET-ABC123XYZ789"),
        "custom secret survived redaction: {}",
        event.message
    );
    assert_eq!(
        event.message, "token *** leaked",
        "message containing a registered custom secret must be redacted"
    );
    reset_secret_patterns_for_tests();
}

#[test]
fn sanitize_context_removes_whole_credential_on_partial_pattern_match() {
    // The jwt pattern matches header.payload; a JWT has THREE dot-separated
    // parts, so redacting the literal match alone would publish the signature.
    let jwt = concat!(
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        ".eyJzdWIiOiIxMjM0NTY3ODkwIn0",
        ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    );
    let signature = jwt.rsplit('.').next().expect("signature segment");
    let mut event = make_event(&format!("auth header {jwt} rejected"));
    sanitize_context(&mut event, 8);
    assert!(
        !event.message.contains(signature),
        "JWT signature survived redaction: {}",
        event.message
    );
    assert_eq!(event.message, "auth header *** rejected");
}

#[test]
fn sanitize_context_leaves_filesystem_paths_alone() {
    // [A-Za-z0-9+/]{40,} includes the slash, so a deep path used to match the
    // base64 rule and the whole message became "***".
    let line = "make -C /home/deploy/apps/production/current/native/capture install";
    let mut event = make_event(line);
    sanitize_context(&mut event, 8);
    assert_eq!(event.message, line);
}
