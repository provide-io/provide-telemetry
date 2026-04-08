// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use regex::Regex;
use std::sync::OnceLock;

use crate::errors::EventSchemaError;

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
