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
}

impl Counter {
    pub fn add(&self, value: f64, _attributes: Option<BTreeMap<String, String>>) {
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
            .expect("counter state lock poisoned")
            .value += value;
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
}

impl Gauge {
    pub fn add(&self, value: f64, _attributes: Option<BTreeMap<String, String>>) {
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
            .last_value += value;
        release(ticket);
    }

    pub fn set(&self, value: f64, _attributes: Option<BTreeMap<String, String>>) {
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
}

impl Histogram {
    pub fn record(&self, value: f64, _attributes: Option<BTreeMap<String, String>>) {
        if !metrics_enabled() {
            return;
        }
        if !should_sample(Signal::Metrics, Some(&self.name)).unwrap_or(true) {
            return;
        }
        let Some(ticket) = try_acquire(Signal::Metrics) else {
            return;
        };
        let mut state = self.state.lock().expect("histogram state lock poisoned");
        state.count += 1;
        state.total += value;
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
    Counter {
        name: name.to_string(),
        description: description.map(str::to_string),
        unit: unit.map(str::to_string),
        state: Arc::new(Mutex::new(CounterState::default())),
    }
}

pub fn gauge(name: &str, description: Option<&str>, unit: Option<&str>) -> Gauge {
    METRICS_INITIALIZED.store(true, Ordering::SeqCst);
    Gauge {
        name: name.to_string(),
        description: description.map(str::to_string),
        unit: unit.map(str::to_string),
        state: Arc::new(Mutex::new(GaugeState::default())),
    }
}

pub fn histogram(name: &str, description: Option<&str>, unit: Option<&str>) -> Histogram {
    METRICS_INITIALIZED.store(true, Ordering::SeqCst);
    Histogram {
        name: name.to_string(),
        description: description.map(str::to_string),
        unit: unit.map(str::to_string),
        state: Arc::new(Mutex::new(HistogramState::default())),
    }
}

pub fn metrics_initialized_for_tests() -> bool {
    METRICS_INITIALIZED.load(Ordering::SeqCst)
}

pub fn reset_metrics_for_tests() {
    METRICS_INITIALIZED.store(false, Ordering::SeqCst);
}
