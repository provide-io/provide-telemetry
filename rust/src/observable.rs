// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Observable (callback-reported) instruments.
//!
//! See `prometheus_metrics.observable_instruments` in `spec/telemetry-api.yaml`.
//! A callback runs at each collection (every scrape for Prometheus, every
//! export interval for OTLP) and returns the current observations. Like the
//! synchronous instruments, an observable binds to the meter provider live at
//! creation: create it after `setup_telemetry`, or its callback never runs.

use std::collections::BTreeMap;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;

use crate::consent::should_allow;
use crate::health::increment_emitted;
use crate::runtime::get_runtime_config;
use crate::sampling::Signal;

/// One value an observable instrument's callback reports.
#[derive(Clone, Debug, PartialEq)]
pub struct Observation {
    pub value: f64,
    pub attributes: Option<BTreeMap<String, String>>,
}

impl Observation {
    /// An observation with no attributes.
    pub fn new(value: f64) -> Self {
        Self {
            value,
            attributes: None,
        }
    }

    /// An observation carrying `attributes` as labels.
    pub fn with_attributes(value: f64, attributes: BTreeMap<String, String>) -> Self {
        Self {
            value,
            attributes: Some(attributes),
        }
    }
}

/// The kinds of observable instrument.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum ObservableKind {
    Counter,
    Gauge,
    UpDownCounter,
}

/// State shared between a handle and the callback registered with the provider.
#[derive(Debug)]
pub(crate) struct Shared {
    name: String,
    registered: AtomicBool,
    #[cfg_attr(not(feature = "otel"), allow(dead_code))] // read by collect()
    failures: AtomicU64,
}

/// A registered observable; [`ObservableInstrument::unregister`] stops its callback.
pub struct ObservableInstrument {
    shared: Arc<Shared>,
    /// Keeps the OTel instrument alive for as long as the handle is.
    #[cfg(feature = "otel")]
    _instrument: Option<Box<dyn std::any::Any + Send + Sync>>,
}

impl std::fmt::Debug for ObservableInstrument {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ObservableInstrument")
            .field("name", &self.shared.name)
            .field("registered", &self.registered())
            .finish()
    }
}

impl ObservableInstrument {
    pub fn name(&self) -> &str {
        &self.shared.name
    }

    /// Whether the callback is attached to a provider and not unregistered.
    pub fn registered(&self) -> bool {
        self.shared.registered.load(Ordering::Acquire)
    }

    /// Stop the callback. Calling it again, or on an unattached instrument, is a no-op.
    pub fn unregister(&self) {
        self.shared.registered.store(false, Ordering::Release);
    }
}

/// The collection-time metrics gates: the runtime enabled flag and consent.
#[cfg_attr(not(feature = "otel"), allow(dead_code))] // only providers collect
fn metrics_allowed() -> bool {
    let enabled = get_runtime_config().map_or(true, |config| config.metrics.enabled);
    enabled && should_allow("metrics", None)
}

/// Run `callback` for one collection, honouring the gates. A panicking
/// callback contributes nothing, and only its first failure is reported.
#[cfg_attr(not(feature = "otel"), allow(dead_code))] // only providers collect
pub(crate) fn collect<F>(shared: &Shared, callback: &F) -> Vec<Observation>
where
    F: Fn() -> Vec<Observation>,
{
    if !shared.registered.load(Ordering::Acquire) || !metrics_allowed() {
        return Vec::new();
    }
    match catch_unwind(AssertUnwindSafe(callback)) {
        Ok(observations) => {
            increment_emitted(Signal::Metrics, observations.len() as u64);
            observations
        }
        Err(_) => {
            note_failure(shared);
            Vec::new()
        }
    }
}

/// Count a failed collection; true the first time, when the one warning is logged.
#[cfg_attr(not(feature = "otel"), allow(dead_code))] // only providers collect
fn note_failure(shared: &Shared) -> bool {
    let first = shared.failures.fetch_add(1, Ordering::AcqRel) == 0;
    if first {
        eprintln!(
            "provide_telemetry: metrics.observable_callback_failed instrument={}",
            shared.name
        );
    }
    first
}

fn register<F>(
    kind: ObservableKind,
    name: &str,
    callback: F,
    description: Option<&str>,
    unit: Option<&str>,
) -> ObservableInstrument
where
    F: Fn() -> Vec<Observation> + Send + Sync + 'static,
{
    let shared = Arc::new(Shared {
        name: name.to_string(),
        registered: AtomicBool::new(false),
        failures: AtomicU64::new(0),
    });
    #[cfg(feature = "otel")]
    {
        let instrument = crate::otel::observable::register(
            kind,
            crate::otel::metrics::InstrumentMeta {
                name,
                description,
                unit,
            },
            Arc::clone(&shared),
            callback,
        );
        shared
            .registered
            .store(instrument.is_some(), Ordering::Release);
        ObservableInstrument {
            shared,
            _instrument: instrument,
        }
    }
    #[cfg(not(feature = "otel"))]
    {
        let _ = (kind, callback, description, unit);
        ObservableInstrument { shared }
    }
}

/// Register `callback` as a monotonic counter reporting cumulative totals.
pub fn observable_counter<F>(
    name: &str,
    callback: F,
    description: Option<&str>,
    unit: Option<&str>,
) -> ObservableInstrument
where
    F: Fn() -> Vec<Observation> + Send + Sync + 'static,
{
    register(ObservableKind::Counter, name, callback, description, unit)
}

/// Register `callback` as a gauge; a series it stops reporting disappears from
/// the next collection.
pub fn observable_gauge<F>(
    name: &str,
    callback: F,
    description: Option<&str>,
    unit: Option<&str>,
) -> ObservableInstrument
where
    F: Fn() -> Vec<Observation> + Send + Sync + 'static,
{
    register(ObservableKind::Gauge, name, callback, description, unit)
}

/// Register `callback` as a non-monotonic sum.
pub fn observable_up_down_counter<F>(
    name: &str,
    callback: F,
    description: Option<&str>,
    unit: Option<&str>,
) -> ObservableInstrument
where
    F: Fn() -> Vec<Observation> + Send + Sync + 'static,
{
    register(
        ObservableKind::UpDownCounter,
        name,
        callback,
        description,
        unit,
    )
}

#[cfg(test)]
#[path = "observable_tests.rs"]
mod tests;
