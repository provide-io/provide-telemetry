// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! PROVIDE_METRICS_HEALTH_OTLP: the health series as observable instruments.
//!
//! See `prometheus_metrics.health_metrics.health_otlp` in
//! `spec/telemetry-api.yaml`. Each health family becomes one observable
//! instrument, named verbatim with no unit or description, on the provider
//! setup installs, so the series reach OTLP too. Values come from a fresh
//! health snapshot at each collection. They describe the SDK rather than user
//! data, so they are not consent-gated and do not count toward
//! `emitted_metrics`. The pull renderer skips them
//! (`prometheus::is_health_metric`), so a scrape carries only the collector's copy.

use opentelemetry::metrics::{AsyncInstrument, MeterProvider as _};
use opentelemetry::KeyValue;
use opentelemetry_sdk::metrics::SdkMeterProvider;

use super::metrics::METER_NAME;
use crate::health::{get_health_snapshot, HealthSnapshot};
use crate::prometheus::health_families;
use crate::prometheus::render::PromType;

/// Report `name`'s samples from a fresh snapshot.
fn observe(name: &str, observer: &dyn AsyncInstrument<f64>) {
    let families = health_families(&get_health_snapshot());
    for sample in families
        .into_iter()
        .filter(|family| family.name == name)
        .flat_map(|family| family.samples)
    {
        let attributes: Vec<KeyValue> = sample
            .labels
            .into_iter()
            .map(|(key, value)| KeyValue::new(key, value))
            .collect();
        observer.observe(sample.value, &attributes);
    }
}

/// Register one observable per health family on `provider`. The SDK keeps an
/// observable's callback for the provider's lifetime, so the handles need no
/// keeping: they stop when the provider shuts down.
pub(super) fn register(provider: &SdkMeterProvider) {
    let meter = provider.meter(METER_NAME);
    for family in health_families(&HealthSnapshot::default()) {
        let name = family.name.clone();
        let callback = move |observer: &dyn AsyncInstrument<f64>| observe(&name, observer);
        match family.kind {
            PromType::Counter => {
                meter
                    .f64_observable_counter(family.name)
                    .with_callback(callback)
                    .build();
            }
            _ => {
                meter
                    .f64_observable_gauge(family.name)
                    .with_callback(callback)
                    .build();
            }
        }
    }
}

#[cfg(test)]
#[path = "health_otlp_tests.rs"]
mod tests;
