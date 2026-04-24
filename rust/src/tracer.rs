// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;
use std::sync::atomic::{AtomicU64, Ordering};

use crate::backpressure::{release, try_acquire, QueueTicket};
#[cfg(feature = "governance")]
use crate::consent::should_allow;
use crate::context::{set_trace_context_internal, trace_snapshot, ContextGuard};
use crate::health::increment_emitted;
use crate::sampling::{should_sample, Signal};

// When the governance feature is disabled, consent is unconditionally granted.
#[cfg(not(feature = "governance"))]
#[inline(always)]
fn should_allow(_signal: &str, _level: Option<&str>) -> bool {
    true
}

pub struct NoopSpan {
    trace_id: String,
    span_id: String,
    guard: Option<ContextGuard>,
}

struct ActiveTrace {
    ticket: Option<QueueTicket>,
    noop_span: Option<NoopSpan>,
    #[cfg(feature = "otel")]
    otel_span: Option<crate::otel::traces::OtelSpanGuard>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Tracer {
    name: String,
}

pub static tracer: std::sync::LazyLock<Tracer> = std::sync::LazyLock::new(|| Tracer::new(None));

impl Tracer {
    pub fn new(name: Option<&str>) -> Self {
        Self {
            name: name.unwrap_or("provide.telemetry").to_string(),
        }
    }

    pub fn name(&self) -> &str {
        &self.name
    }

    pub fn start_span(&self, _name: &str) -> NoopSpan {
        let trace_id = next_hex(32);
        let span_id = next_hex(16);
        let guard = set_trace_context(Some(trace_id.clone()), Some(span_id.clone()));
        NoopSpan {
            trace_id,
            span_id,
            guard: Some(guard),
        }
    }
}

static TRACE_COUNTER: AtomicU64 = AtomicU64::new(1);

fn next_hex(len: usize) -> String {
    let seed = TRACE_COUNTER.fetch_add(1, Ordering::Relaxed);
    let mut value = format!("{seed:016x}");
    while value.len() < len {
        let snapshot = TRACE_COUNTER.fetch_add(1, Ordering::Relaxed);
        value.push_str(&format!("{snapshot:016x}"));
    }
    value[..len].to_string()
}

pub fn get_tracer(name: Option<&str>) -> Tracer {
    Tracer::new(name)
}

pub fn set_trace_context(trace_id: Option<String>, span_id: Option<String>) -> ContextGuard {
    set_trace_context_internal(trace_id, span_id)
}

pub fn get_trace_context() -> BTreeMap<String, Option<String>> {
    let snapshot = trace_snapshot();
    BTreeMap::from([
        ("trace_id".to_string(), snapshot.trace_id),
        ("span_id".to_string(), snapshot.span_id),
    ])
}

fn begin_trace(name: &str) -> Option<ActiveTrace> {
    if !should_allow("traces", None) {
        return None;
    }
    if !should_sample(Signal::Traces, Some(name)).unwrap_or(true) {
        return None;
    }
    let acquired = try_acquire(Signal::Traces);
    if acquired.is_none() {
        return None;
    }
    let ticket = acquired.expect("trace ticket must exist after none guard");

    // When OTel is compiled in and a TracerProvider has been installed,
    // route through the OTel SDK so the span lands at the configured
    // OTLP endpoint. Otherwise fall back to the noop span (which still
    // populates the trace_id / span_id contextvars from synthetic ids).
    #[cfg(feature = "otel")]
    {
        if crate::otel::traces::tracer_provider_installed() {
            increment_emitted(Signal::Traces, 1);
            return Some(ActiveTrace {
                ticket: Some(ticket),
                noop_span: None,
                otel_span: Some(crate::otel::traces::start_span(name)),
            });
        }
    }

    increment_emitted(Signal::Traces, 1);
    Some(ActiveTrace {
        ticket: Some(ticket),
        noop_span: Some(tracer.start_span(name)),
        #[cfg(feature = "otel")]
        otel_span: None,
    })
}

pub fn trace<T, F>(name: &str, callback: F) -> T
where
    F: FnOnce() -> T,
{
    let _active = begin_trace(name);
    callback()
}

impl NoopSpan {
    pub fn trace_id(&self) -> &str {
        &self.trace_id
    }

    pub fn span_id(&self) -> &str {
        &self.span_id
    }

    pub fn set_attribute(&self, _key: &str, _value: &str) {}

    pub fn record_error(&self, _error: &str) {}
}

impl Drop for NoopSpan {
    fn drop(&mut self) {
        drop(self.guard.take());
    }
}

impl Drop for ActiveTrace {
    fn drop(&mut self) {
        #[cfg(feature = "otel")]
        drop(self.otel_span.take());
        drop(self.noop_span.take());
        if let Some(ticket) = self.ticket.take() {
            release(ticket);
        }
    }
}

#[cfg(test)]
#[path = "tracer_tests.rs"]
mod tests;
