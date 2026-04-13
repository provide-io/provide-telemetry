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

    // Probabilistic sampling: uniform random < rate, regardless of key.
    // A key may select an override rate but the sampling decision is always random.
    let keep = rand::random::<f64>() < rate;
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::health::{_reset_health_for_tests, get_health_snapshot};
    use crate::testing::acquire_test_state_lock;

    #[test]
    fn sampling_test_boundary_rates_and_reset_helper() {
        let _guard = acquire_test_state_lock();
        _reset_sampling_for_tests();
        set_sampling_policy(
            Signal::Logs,
            SamplingPolicy {
                default_rate: 0.0,
                overrides: BTreeMap::new(),
            },
        )
        .expect("policy should set");
        assert!(!should_sample(Signal::Logs, None).expect("sampling should work"));

        set_sampling_policy(
            Signal::Logs,
            SamplingPolicy {
                default_rate: 1.0,
                overrides: BTreeMap::new(),
            },
        )
        .expect("policy should set");
        assert!(should_sample(Signal::Logs, None).expect("sampling should work"));

        set_sampling_policy(
            Signal::Logs,
            SamplingPolicy {
                default_rate: 0.25,
                overrides: BTreeMap::from([("special".to_string(), 0.75)]),
            },
        )
        .expect("policy should set");
        _reset_sampling_for_tests();
        let reset = get_sampling_policy(Signal::Logs).expect("policy should exist");
        assert_eq!(reset.default_rate, 1.0);
        assert!(reset.overrides.is_empty());
    }

    #[test]
    fn sampling_test_probabilistic_rate_half_produces_roughly_half() {
        let _guard = acquire_test_state_lock();
        _reset_sampling_for_tests();
        _reset_health_for_tests();

        set_sampling_policy(
            Signal::Logs,
            SamplingPolicy {
                default_rate: 0.5,
                overrides: BTreeMap::from([("override_key".to_string(), 0.5)]),
            },
        )
        .expect("policy should set");

        // Over 10_000 trials at rate 0.5, expect 40–60% sampled (probabilistic).
        let trials = 10_000;
        let kept_no_key = (0..trials)
            .filter(|_| should_sample(Signal::Logs, None).expect("sampling should work"))
            .count();
        assert!(
            kept_no_key >= 4_000 && kept_no_key <= 6_000,
            "rate=0.5 no-key: {kept_no_key}/10000 outside [4000,6000]"
        );

        // Keyed calls look up the override rate but are still probabilistic.
        let kept_keyed = (0..trials)
            .filter(|_| {
                should_sample(Signal::Logs, Some("override_key")).expect("sampling should work")
            })
            .count();
        assert!(
            kept_keyed >= 4_000 && kept_keyed <= 6_000,
            "rate=0.5 keyed: {kept_keyed}/10000 outside [4000,6000]"
        );

        // dropped_logs should equal sum of dropped (not-kept) events.
        let expected_dropped = (trials - kept_no_key) + (trials - kept_keyed);
        assert_eq!(
            get_health_snapshot().dropped_logs as usize,
            expected_dropped,
            "dropped counter mismatch"
        );
    }
}
