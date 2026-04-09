// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;
use std::sync::{Mutex, OnceLock};

use crate::errors::TelemetryError;
use crate::health::increment_dropped;

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum Signal {
    Logs,
    Traces,
    Metrics,
}

#[derive(Clone, Debug, PartialEq)]
pub struct SamplingPolicy {
    pub default_rate: f64,
    pub overrides: BTreeMap<String, f64>,
}

impl Default for SamplingPolicy {
    fn default() -> Self {
        Self {
            default_rate: 1.0,
            overrides: BTreeMap::new(),
        }
    }
}

static POLICIES: OnceLock<Mutex<BTreeMap<Signal, SamplingPolicy>>> = OnceLock::new();

fn policies() -> &'static Mutex<BTreeMap<Signal, SamplingPolicy>> {
    POLICIES.get_or_init(|| {
        Mutex::new(BTreeMap::from([
            (Signal::Logs, SamplingPolicy::default()),
            (Signal::Traces, SamplingPolicy::default()),
            (Signal::Metrics, SamplingPolicy::default()),
        ]))
    })
}

pub fn set_sampling_policy(
    signal: Signal,
    policy: SamplingPolicy,
) -> Result<SamplingPolicy, TelemetryError> {
    let normalized = SamplingPolicy {
        default_rate: policy.default_rate.clamp(0.0, 1.0),
        overrides: policy
            .overrides
            .into_iter()
            .map(|(key, rate)| (key, rate.clamp(0.0, 1.0)))
            .collect(),
    };
    policies()
        .lock()
        .expect("sampling policy lock poisoned")
        .insert(signal, normalized.clone());
    Ok(normalized)
}

pub fn get_sampling_policy(signal: Signal) -> Result<SamplingPolicy, TelemetryError> {
    policies()
        .lock()
        .expect("sampling policy lock poisoned")
        .get(&signal)
        .cloned()
        .ok_or_else(|| TelemetryError::new("unknown signal"))
}

pub fn should_sample(signal: Signal, key: Option<&str>) -> Result<bool, TelemetryError> {
    let policy = get_sampling_policy(signal)?;
    let rate = key
        .and_then(|value| policy.overrides.get(value).copied())
        .unwrap_or(policy.default_rate);

    if rate >= 1.0 {
        return Ok(true);
    }
    if rate <= 0.0 {
        increment_dropped(signal, 1);
        return Ok(false);
    }

    let keep = key
        .map(|value| {
            let total = value
                .as_bytes()
                .iter()
                .fold(0u64, |acc, byte| acc + u64::from(*byte));
            let normalized = (total % 100) as f64 / 100.0;
            normalized < rate
        })
        .unwrap_or(rate >= 0.5);
    if !keep {
        increment_dropped(signal, 1);
    }
    Ok(keep)
}

pub fn _reset_sampling_for_tests() {
    *policies().lock().expect("sampling policy lock poisoned") = BTreeMap::from([
        (Signal::Logs, SamplingPolicy::default()),
        (Signal::Traces, SamplingPolicy::default()),
        (Signal::Metrics, SamplingPolicy::default()),
    ]);
}
