// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

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
    if let Some(baggage) = context.baggage.clone() {
        fields.push(("baggage".to_string(), Value::String(baggage)));
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
