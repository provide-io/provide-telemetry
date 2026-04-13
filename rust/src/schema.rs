// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use regex::Regex;
use std::sync::{OnceLock, atomic::{AtomicBool, Ordering}};

use crate::errors::EventSchemaError;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Event {
    pub event: String,
    pub domain: String,
    pub action: String,
    pub resource: Option<String>,
    pub status: String,
}

static STRICT_SCHEMA: AtomicBool = AtomicBool::new(false);

/// Enable or disable strict segment-format validation for `event()`. Thread-safe.
pub fn set_strict_schema(enabled: bool) {
    STRICT_SCHEMA.store(enabled, Ordering::Relaxed);
}

/// Return the current strict-schema flag value.
pub fn get_strict_schema() -> bool {
    STRICT_SCHEMA.load(Ordering::Relaxed)
}

fn segment_re() -> &'static Regex {
    static SEGMENT_RE: OnceLock<Regex> = OnceLock::new();
    SEGMENT_RE.get_or_init(|| Regex::new(r"^[a-z][a-z0-9_]*$").expect("valid regex"))
}

pub fn event(segments: &[&str]) -> Result<Event, EventSchemaError> {
    if !(3..=4).contains(&segments.len()) {
        return Err(EventSchemaError::new(format!(
            "event() requires 3 or 4 segments (DA[R]S), got {}",
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
