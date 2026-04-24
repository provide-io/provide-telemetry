// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;

use serde_json::Value;

use crate::context::{bind_context, ContextGuard};
use crate::tracer::set_trace_context;

const MAX_HEADER_LENGTH: usize = 512;
const MAX_TRACESTATE_PAIRS: usize = 32;
const MAX_BAGGAGE_LENGTH: usize = 8192;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PropagationContext {
    pub traceparent: Option<String>,
    pub tracestate: Option<String>,
    pub baggage: Option<String>,
    pub trace_id: Option<String>,
    pub span_id: Option<String>,
}

pub struct PropagationGuard {
    trace_guard: Option<ContextGuard>,
    context_guard: Option<ContextGuard>,
}

impl Drop for PropagationGuard {
    #[cfg_attr(test, mutants::skip)] // Equivalent mutant: fields still drop after an empty body.
    fn drop(&mut self) {
        drop(self.trace_guard.take());
        drop(self.context_guard.take());
    }
}

/// Parse a W3C baggage header into key-value pairs.
/// Properties after `;` are stripped. Empty keys are skipped.
pub fn parse_baggage(raw: &str) -> BTreeMap<String, String> {
    let mut result = BTreeMap::new();
    for member in raw.split(',') {
        let kv = member.split(';').next().unwrap_or("");
        if let Some(eq_idx) = kv.find('=') {
            let key = kv[..eq_idx].trim();
            if !key.is_empty() {
                let value = kv[eq_idx + 1..].trim();
                result.insert(key.to_string(), value.to_string());
            }
        }
    }
    result
}

fn parse_traceparent(value: Option<&str>) -> (Option<String>, Option<String>, Option<String>) {
    let Some(raw) = value else {
        return (None, None, None);
    };
    let parts = raw.split('-').collect::<Vec<_>>();
    if parts.len() != 4 {
        return (None, None, None);
    }
    let version = parts[0];
    let trace_id = parts[1];
    let span_id = parts[2];
    let flags = parts[3];
    let valid = version.len() == 2
        && trace_id.len() == 32
        && span_id.len() == 16
        && flags.len() == 2
        && !version.eq_ignore_ascii_case("ff")
        && trace_id != "00000000000000000000000000000000"
        && span_id != "0000000000000000"
        && [version, trace_id, span_id, flags]
            .iter()
            .all(|part| part.chars().all(|ch| ch.is_ascii_hexdigit()));

    if !valid {
        return (None, None, None);
    }

    (
        Some(raw.to_string()),
        Some(trace_id.to_ascii_lowercase()),
        Some(span_id.to_ascii_lowercase()),
    )
}

pub fn extract_w3c_context(
    traceparent: Option<&str>,
    tracestate: Option<&str>,
    baggage: Option<&str>,
) -> PropagationContext {
    let traceparent = traceparent.and_then(|value| {
        if value.len() > MAX_HEADER_LENGTH {
            None
        } else {
            Some(value)
        }
    });
    let tracestate = tracestate.and_then(|value| {
        if value.len() > MAX_HEADER_LENGTH || value.split(',').count() > MAX_TRACESTATE_PAIRS {
            None
        } else {
            Some(value.to_string())
        }
    });
    let baggage = baggage.and_then(|value| {
        if value.len() > MAX_BAGGAGE_LENGTH {
            None
        } else {
            Some(value.to_string())
        }
    });
    let (traceparent, trace_id, span_id) = parse_traceparent(traceparent);

    PropagationContext {
        traceparent,
        tracestate,
        baggage,
        trace_id,
        span_id,
    }
}

pub fn bind_propagation_context(context: PropagationContext) -> PropagationGuard {
    let mut fields = Vec::new();
    if let Some(traceparent) = context.traceparent.clone() {
        fields.push(("traceparent".to_string(), Value::String(traceparent)));
    }
    if let Some(tracestate) = context.tracestate.clone() {
        fields.push(("tracestate".to_string(), Value::String(tracestate)));
    }
    if let Some(ref baggage) = context.baggage {
        fields.push(("baggage".to_string(), Value::String(baggage.clone())));
        for (k, v) in parse_baggage(baggage) {
            fields.push((format!("baggage.{k}"), Value::String(v)));
        }
    }

    let context_guard = if fields.is_empty() {
        None
    } else {
        Some(bind_context(fields))
    };
    let trace_guard = if context.trace_id.is_some() || context.span_id.is_some() {
        Some(set_trace_context(context.trace_id, context.span_id))
    } else {
        None
    };

    PropagationGuard {
        trace_guard,
        context_guard,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use serde_json::json;

    use crate::context::get_context;
    use crate::testing::acquire_test_state_lock;
    use crate::tracer::get_trace_context;

    #[test]
    fn propagation_test_a_parse_baggage_keeps_pairs_and_strips_parameters() {
        let baggage = parse_baggage("user=alice;prop=x,env=prod;ttl=100,invalid,=skip");

        assert_eq!(baggage.get("user").map(String::as_str), Some("alice"));
        assert_eq!(baggage.get("env").map(String::as_str), Some("prod"));
        assert_eq!(baggage.len(), 2);
    }

    #[test]
    fn propagation_test_a_bind_propagation_context_roundtrip_restores_state() {
        let _guard = acquire_test_state_lock();
        let context = PropagationContext {
            traceparent: Some(
                "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01".to_string(),
            ),
            tracestate: Some("k=v".to_string()),
            baggage: Some("user=alice,env=prod".to_string()),
            trace_id: Some("4bf92f3577b34da6a3ce929d0e0e4736".to_string()),
            span_id: Some("00f067aa0ba902b7".to_string()),
        };

        {
            let _propagation = bind_propagation_context(context);
            let trace = get_trace_context();
            let fields = get_context();
            assert_eq!(
                trace.get("trace_id").and_then(std::clone::Clone::clone),
                Some("4bf92f3577b34da6a3ce929d0e0e4736".to_string())
            );
            assert_eq!(
                trace.get("span_id").and_then(std::clone::Clone::clone),
                Some("00f067aa0ba902b7".to_string())
            );
            assert_eq!(
                fields.get("traceparent"),
                Some(&json!(
                    "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
                ))
            );
            assert_eq!(fields.get("tracestate"), Some(&json!("k=v")));
            assert_eq!(fields.get("baggage"), Some(&json!("user=alice,env=prod")));
            assert_eq!(fields.get("baggage.user"), Some(&json!("alice")));
            assert_eq!(fields.get("baggage.env"), Some(&json!("prod")));
        }

        assert!(get_context().is_empty());
        let trace = get_trace_context();
        assert_eq!(trace.get("trace_id"), Some(&None));
        assert_eq!(trace.get("span_id"), Some(&None));
    }
}
