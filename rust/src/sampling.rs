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
    fn sampling_test_keyed_hashing_hits_threshold_edges() {
        let _guard = acquire_test_state_lock();
        _reset_sampling_for_tests();
        _reset_health_for_tests();
        let before = get_health_snapshot().dropped_logs;
        set_sampling_policy(
            Signal::Logs,
            SamplingPolicy {
                default_rate: 0.5,
                overrides: BTreeMap::from([("edge".to_string(), 0.5)]),
            },
        )
        .expect("policy should set");

        let after_first_keep = get_health_snapshot().dropped_logs;
        assert!(should_sample(Signal::Logs, Some("1")).expect("sampling should work"));
        assert_eq!(get_health_snapshot().dropped_logs, after_first_keep);

        assert!(!should_sample(Signal::Logs, Some("11")).expect("sampling should work"));
        let after_first_drop = get_health_snapshot().dropped_logs;
        assert_eq!(after_first_drop - before, 1);

        assert!(!should_sample(Signal::Logs, Some("2")).expect("sampling should work"));
        let after_second_drop = get_health_snapshot().dropped_logs;
        assert_eq!(after_second_drop - before, 2);

        assert!(should_sample(Signal::Logs, None).expect("sampling should work"));
        let after = get_health_snapshot().dropped_logs;
        assert_eq!(after - before, 2);
    }

    #[test]
    fn sampling_test_unknown_policy_errors_when_internal_state_is_missing() {
        let _guard = acquire_test_state_lock();
        policies()
            .lock()
            .expect("sampling policy lock poisoned")
            .clear();

        let err = get_sampling_policy(Signal::Logs).expect_err("missing policy must error");
        assert!(err.message.contains("unknown signal"));

        let err = should_sample(Signal::Logs, None).expect_err("missing policy must bubble up");
        assert!(err.message.contains("unknown signal"));

        _reset_sampling_for_tests();
    }
}
