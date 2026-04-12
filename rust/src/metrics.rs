// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use crate::backpressure::{release, try_acquire};
use crate::runtime::get_runtime_config;
use crate::sampling::{should_sample, Signal};

static METRICS_INITIALIZED: AtomicBool = AtomicBool::new(false);

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Meter {
    name: String,
}

impl Meter {
    pub fn name(&self) -> &str {
        &self.name
    }
}

#[derive(Clone, Debug, Default)]
struct CounterState {
    value: f64,
}

#[derive(Clone, Debug)]
pub struct Counter {
    name: String,
    #[allow(dead_code)]
    description: Option<String>,
    #[allow(dead_code)]
    unit: Option<String>,
    state: Arc<Mutex<CounterState>>,
    #[cfg(feature = "otel")]
    otel: Option<opentelemetry::metrics::Counter<u64>>,
}

impl Counter {
    pub fn add(&self, value: f64, attributes: Option<BTreeMap<String, String>>) {
        if !metrics_enabled() {
            return;
        }
        if !should_sample(Signal::Metrics, Some(&self.name)).unwrap_or(true) {
            return;
        }
        let Some(ticket) = try_acquire(Signal::Metrics) else {
            return;
        };
        // Always update in-process state for value() readback
        self.state
            .lock()
            .expect("counter state lock poisoned")
            .value += value;
        // Also record to OTel global meter when wired
        #[cfg(feature = "otel")]
        if let Some(ref c) = self.otel {
            use opentelemetry::KeyValue;
            let kvs: Vec<KeyValue> = attributes
                .unwrap_or_default()
                .into_iter()
                .map(|(k, v)| KeyValue::new(k, v))
                .collect();
            c.add(value as u64, &kvs);
        }
        #[cfg(not(feature = "otel"))]
        let _ = attributes;
        release(ticket);
    }

    pub fn value(&self) -> f64 {
        self.state
            .lock()
            .expect("counter state lock poisoned")
            .value
    }
}

#[derive(Clone, Debug, Default)]
struct GaugeState {
    last_value: f64,
}

#[derive(Clone, Debug)]
pub struct Gauge {
    name: String,
    #[allow(dead_code)]
    description: Option<String>,
    #[allow(dead_code)]
    unit: Option<String>,
    state: Arc<Mutex<GaugeState>>,
    #[cfg(feature = "otel")]
    otel: Option<opentelemetry::metrics::Gauge<f64>>,
}

impl Gauge {
    pub fn add(&self, value: f64, attributes: Option<BTreeMap<String, String>>) {
        if !metrics_enabled() {
            return;
        }
        if !should_sample(Signal::Metrics, Some(&self.name)).unwrap_or(true) {
            return;
        }
        let Some(ticket) = try_acquire(Signal::Metrics) else {
            return;
        };
        let new_value = {
            let mut state = self.state.lock().expect("gauge state lock poisoned");
            state.last_value += value;
            state.last_value
        };
        #[cfg(feature = "otel")]
        if let Some(ref g) = self.otel {
            use opentelemetry::KeyValue;
            let kvs: Vec<KeyValue> = attributes
                .unwrap_or_default()
                .into_iter()
                .map(|(k, v)| KeyValue::new(k, v))
                .collect();
            g.record(new_value, &kvs);
        }
        #[cfg(not(feature = "otel"))]
        let _ = (new_value, attributes);
        release(ticket);
    }

    pub fn set(&self, value: f64, attributes: Option<BTreeMap<String, String>>) {
        if !metrics_enabled() {
            return;
        }
        if !should_sample(Signal::Metrics, Some(&self.name)).unwrap_or(true) {
            return;
        }
        let Some(ticket) = try_acquire(Signal::Metrics) else {
            return;
        };
        self.state
            .lock()
            .expect("gauge state lock poisoned")
            .last_value = value;
        #[cfg(feature = "otel")]
        if let Some(ref g) = self.otel {
            use opentelemetry::KeyValue;
            let kvs: Vec<KeyValue> = attributes
                .unwrap_or_default()
                .into_iter()
                .map(|(k, v)| KeyValue::new(k, v))
                .collect();
            g.record(value, &kvs);
        }
        #[cfg(not(feature = "otel"))]
        let _ = (value, attributes);
        release(ticket);
    }

    pub fn value(&self) -> f64 {
        self.state
            .lock()
            .expect("gauge state lock poisoned")
            .last_value
    }
}

#[derive(Clone, Debug, Default)]
struct HistogramState {
    count: usize,
    total: f64,
}

#[derive(Clone, Debug)]
pub struct Histogram {
    name: String,
    #[allow(dead_code)]
    description: Option<String>,
    #[allow(dead_code)]
    unit: Option<String>,
    state: Arc<Mutex<HistogramState>>,
    #[cfg(feature = "otel")]
    otel: Option<opentelemetry::metrics::Histogram<f64>>,
}

impl Histogram {
    pub fn record(&self, value: f64, attributes: Option<BTreeMap<String, String>>) {
        if !metrics_enabled() {
            return;
        }
        if !should_sample(Signal::Metrics, Some(&self.name)).unwrap_or(true) {
            return;
        }
        let Some(ticket) = try_acquire(Signal::Metrics) else {
            return;
        };
        {
            let mut state = self.state.lock().expect("histogram state lock poisoned");
            state.count += 1;
            state.total += value;
        }
        #[cfg(feature = "otel")]
        if let Some(ref h) = self.otel {
            use opentelemetry::KeyValue;
            let kvs: Vec<KeyValue> = attributes
                .unwrap_or_default()
                .into_iter()
                .map(|(k, v)| KeyValue::new(k, v))
                .collect();
            h.record(value, &kvs);
        }
        #[cfg(not(feature = "otel"))]
        let _ = attributes;
        release(ticket);
    }

    pub fn count(&self) -> usize {
        self.state
            .lock()
            .expect("histogram state lock poisoned")
            .count
    }

    pub fn total(&self) -> f64 {
        self.state
            .lock()
            .expect("histogram state lock poisoned")
            .total
    }
}

fn metrics_enabled() -> bool {
    get_runtime_config()
        .map(|config| config.metrics.enabled)
        .unwrap_or(true)
}

pub fn get_meter(name: Option<&str>) -> Meter {
    Meter {
        name: name.unwrap_or("provide.telemetry").to_string(),
    }
}

pub fn counter(name: &str, description: Option<&str>, unit: Option<&str>) -> Counter {
    METRICS_INITIALIZED.store(true, Ordering::SeqCst);
    #[cfg(feature = "otel")]
    let otel = if crate::otel::otel_installed() {
        let meter = opentelemetry::global::meter("provide-telemetry");
        let mut builder = meter.u64_counter(name.to_string());
        if let Some(desc) = description {
            builder = builder.with_description(desc.to_string());
        }
        if let Some(u) = unit {
            builder = builder.with_unit(u.to_string());
        }
        Some(builder.build())
    } else {
        None
    };
    Counter {
        name: name.to_string(),
        description: description.map(str::to_string),
        unit: unit.map(str::to_string),
        state: Arc::new(Mutex::new(CounterState::default())),
        #[cfg(feature = "otel")]
        otel,
    }
}

pub fn gauge(name: &str, description: Option<&str>, unit: Option<&str>) -> Gauge {
    METRICS_INITIALIZED.store(true, Ordering::SeqCst);
    #[cfg(feature = "otel")]
    let otel = if crate::otel::otel_installed() {
        let meter = opentelemetry::global::meter("provide-telemetry");
        let mut builder = meter.f64_gauge(name.to_string());
        if let Some(desc) = description {
            builder = builder.with_description(desc.to_string());
        }
        if let Some(u) = unit {
            builder = builder.with_unit(u.to_string());
        }
        Some(builder.build())
    } else {
        None
    };
    Gauge {
        name: name.to_string(),
        description: description.map(str::to_string),
        unit: unit.map(str::to_string),
        state: Arc::new(Mutex::new(GaugeState::default())),
        #[cfg(feature = "otel")]
        otel,
    }
}

pub fn histogram(name: &str, description: Option<&str>, unit: Option<&str>) -> Histogram {
    METRICS_INITIALIZED.store(true, Ordering::SeqCst);
    #[cfg(feature = "otel")]
    let otel = if crate::otel::otel_installed() {
        let meter = opentelemetry::global::meter("provide-telemetry");
        let mut builder = meter.f64_histogram(name.to_string());
        if let Some(desc) = description {
            builder = builder.with_description(desc.to_string());
        }
        if let Some(u) = unit {
            builder = builder.with_unit(u.to_string());
        }
        Some(builder.build())
    } else {
        None
    };
    Histogram {
        name: name.to_string(),
        description: description.map(str::to_string),
        unit: unit.map(str::to_string),
        state: Arc::new(Mutex::new(HistogramState::default())),
        #[cfg(feature = "otel")]
        otel,
    }
}

pub fn metrics_initialized_for_tests() -> bool {
    METRICS_INITIALIZED.load(Ordering::SeqCst)
}

pub fn reset_metrics_for_tests() {
    METRICS_INITIALIZED.store(false, Ordering::SeqCst);
}
