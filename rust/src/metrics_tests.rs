// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use super::*;
use std::collections::BTreeMap;

use crate::backpressure::{set_queue_policy, try_acquire, QueuePolicy};
use crate::health::get_health_snapshot;
use crate::runtime::set_active_config;
use crate::sampling::{set_sampling_policy, SamplingPolicy};
use crate::testing::{acquire_test_state_lock, reset_telemetry_state};
#[cfg(feature = "governance")]
use crate::{reset_consent_for_tests, set_consent_level, ConsentLevel};
use crate::{MetricsConfig, TelemetryConfig};

#[test]
fn metrics_test_meter_names_and_init_flag_follow_constructors() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    assert!(!metrics_initialized_for_tests());
    assert_eq!(get_meter(None).name(), "provide.telemetry");
    assert_eq!(get_meter(Some("custom.meter")).name(), "custom.meter");

    let _counter = counter("test.counter", None, None);
    assert!(metrics_initialized_for_tests());
}

#[test]
fn metrics_test_reset_clears_metrics_initialization_flag() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    let _counter = counter("test.counter", None, None);
    assert!(metrics_initialized_for_tests());

    reset_metrics_for_tests();
    assert!(!metrics_initialized_for_tests());

    let _counter = counter("test.counter.after_reset", None, None);
    assert!(metrics_initialized_for_tests());
}

#[cfg(not(feature = "governance"))]
#[test]
fn metrics_test_non_governance_fallback_allows_metric_mutation() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    let counter_metric = counter("test.counter", None, None);
    let gauge_metric = gauge("test.gauge", None, None);
    let histogram_metric = histogram("test.histogram", None, None);

    counter_metric.add(2.0, None);
    gauge_metric.set(7.0, None);
    gauge_metric.add(-2.0, None);
    histogram_metric.record(4.0, None);

    assert_eq!(counter_metric.value(), 2.0);
    assert_eq!(gauge_metric.value(), 5.0);
    assert_eq!(histogram_metric.count(), 1);
    assert_eq!(histogram_metric.total(), 4.0);
}

#[test]
fn metrics_test_counter_sampling_zero_skips_updates() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    set_sampling_policy(
        Signal::Metrics,
        SamplingPolicy {
            default_rate: 0.0,
            overrides: BTreeMap::new(),
        },
    )
    .expect("sampling policy should set");

    let metric = counter("test.counter", None, None);
    let before = get_health_snapshot();
    metric.add(2.0, None);
    let after = get_health_snapshot();

    assert_eq!(metric.value(), 0.0);
    assert_eq!(after.emitted_metrics, before.emitted_metrics);
    assert_eq!(after.dropped_metrics, before.dropped_metrics + 1);
}

#[test]
fn metrics_test_histogram_queue_full_skips_recording() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    set_queue_policy(QueuePolicy {
        logs_maxsize: 0,
        traces_maxsize: 0,
        metrics_maxsize: 1,
    });

    let held = try_acquire(Signal::Metrics).expect("first metrics acquire should succeed");
    let metric = histogram("test.histogram", None, None);
    let before = get_health_snapshot();
    metric.record(3.0, None);
    release(held);
    let after = get_health_snapshot();

    assert_eq!(metric.count(), 0);
    assert_eq!(metric.total(), 0.0);
    assert_eq!(after.emitted_metrics, before.emitted_metrics);
    assert_eq!(after.dropped_metrics, before.dropped_metrics + 1);
}

#[test]
fn metrics_test_runtime_disable_skips_mutation_of_gauge() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    set_active_config(Some(TelemetryConfig {
        metrics: MetricsConfig {
            enabled: false,
            ..MetricsConfig::default()
        },
        ..TelemetryConfig::default()
    }));

    let metric = gauge("test.gauge", None, None);
    let before = get_health_snapshot();
    metric.set(9.0, None);
    metric.add(1.0, None);
    let after = get_health_snapshot();

    assert_eq!(metric.value(), 0.0);
    assert_eq!(after.emitted_metrics, before.emitted_metrics);
    assert_eq!(after.dropped_metrics, before.dropped_metrics);
}

#[test]
fn metrics_test_positive_paths_record_values_and_increment_health() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    let mut attributes = BTreeMap::new();
    attributes.insert("route".to_string(), "checkout".to_string());

    let counter_metric = counter("test.counter", Some("counter"), Some("count"));
    let gauge_metric = gauge("test.gauge", Some("gauge"), Some("unit"));
    let histogram_metric = histogram("test.histogram", Some("histogram"), Some("ms"));
    let before = get_health_snapshot();

    counter_metric.add(2.0, Some(attributes.clone()));
    counter_metric.add(3.0, None);
    gauge_metric.set(7.0, Some(attributes.clone()));
    gauge_metric.add(-2.0, None);
    histogram_metric.record(4.0, Some(attributes));
    histogram_metric.record(6.0, None);

    let after = get_health_snapshot();
    assert_eq!(counter_metric.value(), 5.0);
    assert_eq!(gauge_metric.value(), 5.0);
    assert_eq!(histogram_metric.count(), 2);
    assert_eq!(histogram_metric.total(), 10.0);
    assert_eq!(after.emitted_metrics, before.emitted_metrics + 6);
}

#[test]
fn metrics_test_counter_guards_cover_disabled_and_queue_full_paths() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    set_active_config(Some(TelemetryConfig {
        metrics: MetricsConfig {
            enabled: false,
            ..MetricsConfig::default()
        },
        ..TelemetryConfig::default()
    }));

    let counter_metric = counter("test.counter.disabled", None, None);
    let before_disabled = get_health_snapshot();
    counter_metric.add(1.0, None);
    let after_disabled = get_health_snapshot();
    assert_eq!(counter_metric.value(), 0.0);
    assert_eq!(
        after_disabled.emitted_metrics,
        before_disabled.emitted_metrics
    );
    assert_eq!(
        after_disabled.dropped_metrics,
        before_disabled.dropped_metrics
    );

    reset_telemetry_state();
    set_queue_policy(QueuePolicy {
        logs_maxsize: 0,
        traces_maxsize: 0,
        metrics_maxsize: 1,
    });
    let held = try_acquire(Signal::Metrics).expect("first metrics acquire should succeed");
    let counter_metric = counter("test.counter.queue", None, None);
    let before_queue = get_health_snapshot();
    counter_metric.add(1.0, None);
    release(held);
    let after_queue = get_health_snapshot();
    assert_eq!(counter_metric.value(), 0.0);
    assert_eq!(after_queue.emitted_metrics, before_queue.emitted_metrics);
    assert_eq!(
        after_queue.dropped_metrics,
        before_queue.dropped_metrics + 1
    );
}

#[test]
fn metrics_test_gauge_guards_cover_sampling_and_queue_full_paths() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    set_sampling_policy(
        Signal::Metrics,
        SamplingPolicy {
            default_rate: 0.0,
            overrides: BTreeMap::new(),
        },
    )
    .expect("sampling policy should set");

    let gauge_metric = gauge("test.gauge.sampling", None, None);
    let before_sampling = get_health_snapshot();
    gauge_metric.add(1.0, None);
    gauge_metric.set(2.0, None);
    let after_sampling = get_health_snapshot();
    assert_eq!(gauge_metric.value(), 0.0);
    assert_eq!(
        after_sampling.emitted_metrics,
        before_sampling.emitted_metrics
    );
    assert_eq!(
        after_sampling.dropped_metrics,
        before_sampling.dropped_metrics + 2
    );

    reset_telemetry_state();
    set_queue_policy(QueuePolicy {
        logs_maxsize: 0,
        traces_maxsize: 0,
        metrics_maxsize: 1,
    });
    let held = try_acquire(Signal::Metrics).expect("first metrics acquire should succeed");
    let gauge_metric = gauge("test.gauge.queue", None, None);
    let before_queue = get_health_snapshot();
    gauge_metric.add(1.0, None);
    gauge_metric.set(2.0, None);
    release(held);
    let after_queue = get_health_snapshot();
    assert_eq!(gauge_metric.value(), 0.0);
    assert_eq!(after_queue.emitted_metrics, before_queue.emitted_metrics);
    assert_eq!(
        after_queue.dropped_metrics,
        before_queue.dropped_metrics + 2
    );
}

#[test]
fn metrics_test_histogram_guards_cover_disabled_and_sampling_paths() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    set_active_config(Some(TelemetryConfig {
        metrics: MetricsConfig {
            enabled: false,
            ..MetricsConfig::default()
        },
        ..TelemetryConfig::default()
    }));

    let histogram_metric = histogram("test.histogram.disabled", None, None);
    let before_disabled = get_health_snapshot();
    histogram_metric.record(1.0, None);
    let after_disabled = get_health_snapshot();
    assert_eq!(histogram_metric.count(), 0);
    assert_eq!(histogram_metric.total(), 0.0);
    assert_eq!(
        after_disabled.emitted_metrics,
        before_disabled.emitted_metrics
    );
    assert_eq!(
        after_disabled.dropped_metrics,
        before_disabled.dropped_metrics
    );

    reset_telemetry_state();
    set_sampling_policy(
        Signal::Metrics,
        SamplingPolicy {
            default_rate: 0.0,
            overrides: BTreeMap::new(),
        },
    )
    .expect("sampling policy should set");
    let histogram_metric = histogram("test.histogram.sampling", None, None);
    let before_sampling = get_health_snapshot();
    histogram_metric.record(1.0, None);
    let after_sampling = get_health_snapshot();
    assert_eq!(histogram_metric.count(), 0);
    assert_eq!(histogram_metric.total(), 0.0);
    assert_eq!(
        after_sampling.emitted_metrics,
        before_sampling.emitted_metrics
    );
    assert_eq!(
        after_sampling.dropped_metrics,
        before_sampling.dropped_metrics + 1
    );
}

#[cfg(feature = "governance")]
#[test]
fn metrics_test_consent_none_blocks_all_metric_mutations() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    set_consent_level(ConsentLevel::None);

    let counter_metric = counter("test.counter", None, None);
    let gauge_metric = gauge("test.gauge", None, None);
    let histogram_metric = histogram("test.histogram", None, None);
    let before = get_health_snapshot();

    counter_metric.add(1.0, None);
    gauge_metric.set(2.0, None);
    gauge_metric.add(3.0, None);
    histogram_metric.record(4.0, None);

    let after = get_health_snapshot();
    assert_eq!(counter_metric.value(), 0.0);
    assert_eq!(gauge_metric.value(), 0.0);
    assert_eq!(histogram_metric.count(), 0);
    assert_eq!(histogram_metric.total(), 0.0);
    assert_eq!(after.emitted_metrics, before.emitted_metrics);
    assert_eq!(after.dropped_metrics, before.dropped_metrics);

    reset_consent_for_tests();
}
