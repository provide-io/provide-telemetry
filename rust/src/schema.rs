// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use regex::Regex;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::OnceLock;

use crate::errors::EventSchemaError;

static STRICT_SCHEMA: AtomicBool = AtomicBool::new(false);

/// Enable or disable strict schema validation for [`event`] segment format.
///
/// When strict mode is disabled (the default), segment format is not validated.
/// When enabled, every segment must match `^[a-z][a-z0-9_]*$`.
/// Segment count validation (3–4) is always enforced regardless of this flag.
pub fn set_strict_schema(enabled: bool) {
    STRICT_SCHEMA.store(enabled, Ordering::SeqCst);
}

pub fn get_strict_schema() -> bool {
    STRICT_SCHEMA.load(Ordering::SeqCst)
}

pub fn _reset_strict_schema_for_tests() {
    STRICT_SCHEMA.store(false, Ordering::SeqCst);
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Event {
    pub event: String,
    pub domain: String,
    pub action: String,
    pub resource: Option<String>,
    pub status: String,
}

fn segment_re() -> &'static Regex {
    static SEGMENT_RE: OnceLock<Regex> = OnceLock::new();
    SEGMENT_RE.get_or_init(|| Regex::new(r"^[a-z][a-z0-9_]*$").expect("valid regex"))
}

pub fn event(segments: &[&str]) -> Result<Event, EventSchemaError> {
    // Segment count is always validated.
    if !(3..=4).contains(&segments.len()) {
        return Err(EventSchemaError::new(format!(
            "event() requires 3 or 4 segments (DA[R]S), got {}",
            segments.len()
        )));
    }

    // Segment format is only validated in strict mode.
    if get_strict_schema() {
        for (idx, segment) in segments.iter().enumerate() {
            if !segment_re().is_match(segment) {
                return Err(EventSchemaError::new(format!(
                    "invalid event segment: segment[{idx}]={segment}"
                )));
            }
        }
    }

    let event = segments.join(".");
    Ok(Event {
        event,
        domain: segments[0].to_string(),
        action: segments[1].to_string(),
        resource: if segments.len() == 4 {
            Some(segments[2].to_string())
        } else {
            None
        },
        status: segments[segments.len() - 1].to_string(),
    })
}

pub fn event_name(segments: &[&str], strict: bool) -> Result<String, EventSchemaError> {
    if strict {
        if !(3..=5).contains(&segments.len()) {
            return Err(EventSchemaError::new(format!(
                "expected 3-5 segments, got {}",
                segments.len()
            )));
        }
        for (idx, segment) in segments.iter().enumerate() {
            if !segment_re().is_match(segment) {
                return Err(EventSchemaError::new(format!(
                    "invalid event segment: segment[{idx}]={segment}"
                )));
            }
        }
    } else if segments.is_empty() {
        return Err(EventSchemaError::new(
            "event_name requires at least 1 segment",
        ));
    }
    Ok(segments.join("."))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testing::acquire_test_state_lock;

    #[test]
    fn schema_test_strict_schema_gate_controls_segment_format_validation() {
        let _guard = acquire_test_state_lock();
        _reset_strict_schema_for_tests();

        // Non-conforming segment (contains hyphen): should succeed in non-strict mode.
        assert!(
            event(&["auth", "login-web", "ok"]).is_ok(),
            "non-strict mode should allow non-conforming segments"
        );

        // Enable strict mode: same event should fail.
        set_strict_schema(true);
        let err = event(&["auth", "login-web", "ok"])
            .expect_err("strict mode should reject non-conforming segments");
        assert!(
            err.message.contains("login-web"),
            "error should mention the invalid segment"
        );

        // Segment count is still enforced regardless of strict mode.
        set_strict_schema(false);
        assert!(
            event(&["only", "two"]).is_err(),
            "too few segments should always fail"
        );
        assert!(
            event(&["a", "b", "c", "d", "e"]).is_err(),
            "too many segments should always fail"
        );

        _reset_strict_schema_for_tests();
    }

    #[test]
    fn schema_test_event_name_returns_exact_joined_value() {
        assert_eq!(
            event_name(&["auth", "login", "ok"], false).expect("name should build"),
            "auth.login.ok"
        );
        assert_eq!(
            event_name(&["a", "b", "c", "d", "e"], true).expect("strict name should build"),
            "a.b.c.d.e"
        );
    }

    #[test]
    fn schema_test_event_name_validates_empty_and_invalid_strict_inputs() {
        let err = event_name(&[], false).expect_err("empty non-strict name should fail");
        assert_eq!(err.message, "event_name requires at least 1 segment");

        let err = event_name(&["a", "b"], true).expect_err("strict arity should fail");
        assert_eq!(err.message, "expected 3-5 segments, got 2");

        let err =
            event_name(&["valid", "not-valid", "ok"], true).expect_err("strict syntax should fail");
        assert_eq!(err.message, "invalid event segment: segment[1]=not-valid");
    }
}
