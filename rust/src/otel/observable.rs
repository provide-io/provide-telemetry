// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Observable instruments on the installed OTel meter provider.

use std::any::Any;
use std::sync::Arc;

use opentelemetry::global;
use opentelemetry::metrics::AsyncInstrument;
use opentelemetry::KeyValue;

use super::metrics::{meter_provider_installed, InstrumentMeta, METER_NAME};
use crate::observable::{collect, ObservableKind, Observation, Shared};

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
    let observe = move |observer: &dyn AsyncInstrument<f64>| {
        report(observer, collect(&shared, &callback));
    };
    let name = meta.name.to_string();
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
