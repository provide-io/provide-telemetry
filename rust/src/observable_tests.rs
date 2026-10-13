// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! prometheus_metrics.observable_instruments: collection-time gates, failure
//! isolation with one warning per instrument, idempotent unregister, and no
//! callback for an observable created before setup.

use super::*;

use std::sync::atomic::AtomicUsize;

use crate::config::TelemetryConfig;
use crate::testing::{acquire_test_state_lock, reset_telemetry_state};

#[mutants::skip] // test helper
fn shared(name: &str, registered: bool) -> Shared {
    Shared {
        name: name.to_string(),
        registered: AtomicBool::new(registered),
        failures: AtomicU64::new(0),
    }
}

#[test]
fn observations_carry_values_and_optional_attributes() {
    assert_eq!(
        Observation::new(1.5),
        Observation {
            value: 1.5,
            attributes: None
        }
    );
    let attrs = BTreeMap::from([("k".to_string(), "v".to_string())]);
    assert_eq!(
        Observation::with_attributes(2.0, attrs.clone()).attributes,
        Some(attrs)
    );
}

#[test]
fn collect_honours_registration_metrics_enabled_and_consent() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    let calls = AtomicUsize::new(0);
    let callback = || {
        calls.fetch_add(1, Ordering::SeqCst);
        vec![Observation::new(1.0), Observation::new(2.0)]
    };

    let live = shared("live", true);
    assert_eq!(collect(&live, &callback).len(), 2);
    assert_eq!(crate::health::get_health_snapshot().emitted_metrics, 2);

    let unregistered = shared("off", false);
    assert!(collect(&unregistered, &callback).is_empty());
    assert_eq!(calls.load(Ordering::SeqCst), 1);

    crate::consent::set_consent_level(crate::consent::ConsentLevel::None);
    assert!(collect(&live, &callback).is_empty());
    crate::consent::reset_consent_for_tests();

    let mut disabled = TelemetryConfig::default();
    disabled.metrics.enabled = false;
    crate::runtime::set_active_config(Some(disabled));
    assert!(collect(&live, &callback).is_empty());
    crate::runtime::set_active_config(None);

    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(crate::health::get_health_snapshot().emitted_metrics, 2);
    reset_telemetry_state();
}

#[test]
fn a_panicking_callback_contributes_nothing_and_warns_once() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    let failing = shared("boom", true);
    let panics = || -> Vec<Observation> { panic!("callback failure") };
    assert!(collect(&failing, &panics).is_empty());
    assert!(collect(&failing, &panics).is_empty());
    assert_eq!(failing.failures.load(Ordering::SeqCst), 2);
    assert_eq!(crate::health::get_health_snapshot().emitted_metrics, 0);

    let fresh = shared("fresh", true);
    assert!(note_failure(&fresh));
    assert!(!note_failure(&fresh));
    reset_telemetry_state();
}

#[test]
fn an_observable_created_before_setup_never_registers() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    let handle = observable_gauge("early.gauge", || vec![Observation::new(1.0)], None, None);
    assert_eq!(handle.name(), "early.gauge");
    assert!(!handle.registered());
    handle.unregister();
    handle.unregister();
    assert!(!handle.registered());
    assert_eq!(
        format!("{handle:?}"),
        "ObservableInstrument { name: \"early.gauge\", registered: false }"
    );
}

#[cfg(feature = "otel")]
#[mutants::skip] // test helper
fn prometheus_config() -> TelemetryConfig {
    let mut config = TelemetryConfig::default();
    config.tracing.enabled = false;
    config.metrics.exporters = vec!["prometheus".to_string()];
    config
}

#[cfg(feature = "otel")]
#[mutants::skip] // test helper
fn scrape() -> String {
    String::from_utf8(crate::prometheus::render_prometheus(None).unwrap().0).unwrap()
}

#[cfg(feature = "otel")]
#[test]
fn observables_report_at_each_scrape_until_unregistered() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();
    crate::setup_telemetry(Some(prometheus_config())).expect("setup");

    let calls = Arc::new(AtomicUsize::new(0));
    let seen = Arc::clone(&calls);
    let counter = observable_counter(
        "jobs.done",
        move || {
            seen.fetch_add(1, Ordering::SeqCst);
            vec![Observation::with_attributes(
                4.0,
                BTreeMap::from([("queue".to_string(), "a".to_string())]),
            )]
        },
        Some("Jobs done"),
        Some("s"),
    );
    let gauge = observable_gauge(
        "room.temperature",
        || vec![Observation::new(21.5)],
        None,
        Some("Cel"),
    );
    let updown =
        observable_up_down_counter("queue.depth", || vec![Observation::new(-2.0)], None, None);
    assert!(counter.registered() && gauge.registered() && updown.registered());

    let text = scrape();
    assert!(
        text.contains("# HELP jobs_done_seconds_total Jobs done\n"),
        "{text}"
    );
    assert!(
        text.contains("# TYPE jobs_done_seconds_total counter\n"),
        "{text}"
    );
    assert!(
        text.contains("jobs_done_seconds_total{queue=\"a\"} 4\n"),
        "{text}"
    );
    assert!(
        text.contains("# TYPE room_temperature_celsius gauge\n"),
        "{text}"
    );
    assert!(text.contains("room_temperature_celsius 21.5\n"), "{text}");
    assert!(text.contains("# TYPE queue_depth gauge\n"), "{text}");
    assert!(text.contains("queue_depth -2\n"), "{text}");
    assert_eq!(calls.load(Ordering::SeqCst), 1);

    counter.unregister();
    counter.unregister();
    assert!(!counter.registered());
    let text = scrape();
    assert!(!text.contains("jobs_done_seconds_total{"), "{text}");
    assert_eq!(calls.load(Ordering::SeqCst), 1);

    crate::shutdown_telemetry(None).expect("shutdown");
    reset_telemetry_state();
}
