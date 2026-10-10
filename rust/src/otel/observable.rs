// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Observable instruments on the installed OTel meter provider.
//!
//! The SDK keeps every series an observable ever reported in a cumulative
//! collection, while the contract says a series its callback stops reporting
//! disappears from the next one. So each callback run records which attribute
//! sets it reported, and the pull reader drops the rest
//! ([`retain_observed`]).

use std::any::Any;
use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Mutex, OnceLock};

use opentelemetry::global;
use opentelemetry::metrics::AsyncInstrument;
use opentelemetry::KeyValue;

use super::metrics::{meter_provider_installed, InstrumentMeta, METER_NAME};
use crate::observable::{collect, ObservableKind, Observation, Shared};
use crate::prometheus::render::{Labels, Points, ResourceView};

/// Attribute sets, sorted by key, that one observable reported in its latest run.
type Reported = HashSet<Labels>;

/// Instrument name -> (observable identity -> what it last reported).
static OBSERVED: OnceLock<Mutex<HashMap<String, HashMap<usize, Reported>>>> = OnceLock::new();

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only swap in Mutex::default().
fn empty_observed() -> Mutex<HashMap<String, HashMap<usize, Reported>>> {
    Mutex::new(HashMap::new())
}

fn observed() -> &'static Mutex<HashMap<String, HashMap<usize, Reported>>> {
    OBSERVED.get_or_init(empty_observed)
}

fn sorted(mut labels: Labels) -> Labels {
    labels.sort();
    labels
}

fn record_observed(name: &str, id: usize, observations: &[Observation]) {
    let reported = observations
        .iter()
        .map(|o| {
            sorted(
                o.attributes
                    .clone()
                    .unwrap_or_default()
                    .into_iter()
                    .collect(),
            )
        })
        .collect();
    crate::_lock::lock(observed())
        .entry(name.to_string())
        .or_default()
        .insert(id, reported);
}

/// Drop the series of our observables that their latest callback run did not report.
pub(crate) fn retain_observed(view: &mut ResourceView) {
    let observed = crate::_lock::lock(observed());
    for scope in view.scopes.iter_mut().filter(|s| s.name == METER_NAME) {
        for metric in &mut scope.metrics {
            let Some(by_handle) = observed.get(&metric.name) else {
                continue;
            };
            let keep = |labels: &Labels| {
                let labels = sorted(labels.clone());
                by_handle
                    .values()
                    .any(|reported| reported.contains(&labels))
            };
            match &mut metric.points {
                Points::Sum { points, .. } | Points::Gauge(points) => {
                    points.retain(|(labels, _)| keep(labels));
                }
                Points::Histogram(_) => {}
            }
        }
    }
}

/// Forget what observables reported; their provider is gone.
pub(crate) fn clear_observed() {
    crate::_lock::lock(observed()).clear();
}

fn report(observer: &dyn AsyncInstrument<f64>, observations: Vec<Observation>) {
    for observation in observations {
        let attributes: Vec<KeyValue> = observation
            .attributes
            .unwrap_or_default()
            .into_iter()
            .map(|(key, value)| KeyValue::new(key, value))
            .collect();
        observer.observe(observation.value, &attributes);
    }
}

/// Register `callback` with the installed provider, or return `None` when we
/// have not installed one: the observable then never runs.
pub(crate) fn register<F>(
    kind: ObservableKind,
    meta: InstrumentMeta<'_>,
    shared: Arc<Shared>,
    callback: F,
) -> Option<Box<dyn Any + Send + Sync>>
where
    F: Fn() -> Vec<Observation> + Send + Sync + 'static,
{
    if !meter_provider_installed() {
        return None;
    }
    let meter = global::meter(METER_NAME);
    let name = meta.name.to_string();
    let id = Arc::as_ptr(&shared) as usize;
    let recorded_as = name.clone();
    let observe = move |observer: &dyn AsyncInstrument<f64>| {
        let observations = collect(&shared, &callback);
        record_observed(&recorded_as, id, &observations);
        report(observer, observations);
    };
    let description = meta.description.unwrap_or("").to_string();
    let unit = meta.unit.unwrap_or("").to_string();
    let instrument: Box<dyn Any + Send + Sync> = match kind {
        ObservableKind::Counter => Box::new(
            meter
                .f64_observable_counter(name)
                .with_description(description)
                .with_unit(unit)
                .with_callback(observe)
                .build(),
        ),
        ObservableKind::Gauge => Box::new(
            meter
                .f64_observable_gauge(name)
                .with_description(description)
                .with_unit(unit)
                .with_callback(observe)
                .build(),
        ),
        ObservableKind::UpDownCounter => Box::new(
            meter
                .f64_observable_up_down_counter(name)
                .with_description(description)
                .with_unit(unit)
                .with_callback(observe)
                .build(),
        ),
    };
    Some(instrument)
}

#[cfg(test)]
#[path = "observable_tests.rs"]
mod tests;
