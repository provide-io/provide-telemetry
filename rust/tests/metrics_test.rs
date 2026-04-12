// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use std::sync::{Mutex, OnceLock};

use provide_telemetry::{counter, gauge, get_meter, histogram, reconfigure_telemetry, reset_metrics_for_tests, TelemetryConfig};

static METRICS_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn metrics_lock() -> &'static Mutex<()> {
    METRICS_LOCK.get_or_init(|| Mutex::new(()))
}

#[test]
fn metrics_test_fallback_instruments_record_values() {
    let requests = counter("test.requests", Some("Total requests"), Some("request"));
    requests.add(2.0, None);
    requests.add(3.0, None);
    assert_eq!(requests.value(), 5.0);

    let queue_depth = gauge("test.queue_depth", Some("Queue depth"), Some("item"));
    queue_depth.set(7.0, None);
    queue_depth.add(-2.0, None);
    assert_eq!(queue_depth.value(), 5.0);

    let latency = histogram("test.latency", Some("Latency"), Some("ms"));
    latency.record(12.0, None);
    latency.record(8.0, None);
    assert_eq!(latency.count(), 2);
    assert_eq!(latency.total(), 20.0);
}

#[test]
fn metrics_test_meter_name_getter() {
    // Kills: replace Meter::name -> &str with "" or "xyzzy"
    let meter = get_meter(Some("my.service.meter"));
    assert_eq!(meter.name(), "my.service.meter");
}

#[test]
fn metrics_test_disabled_metrics_are_no_ops() {
    // Kills: replace metrics_enabled -> bool with true
    // When metrics.enabled=false, counter.add() must not update the value.
    let _guard = metrics_lock().lock().expect("metrics lock poisoned");

    let mut env = std::collections::HashMap::new();
    env.insert("PROVIDE_METRICS_ENABLED".to_string(), "false".to_string());
    let cfg = TelemetryConfig::from_map(&env).expect("config must parse");
    reconfigure_telemetry(Some(cfg)).expect("reconfigure must succeed");

    reset_metrics_for_tests();
    let c = counter("test.disabled", None, None);
    c.add(99.0, None);
    assert_eq!(c.value(), 0.0, "add() must be a no-op when metrics are disabled");

    // Restore default (metrics enabled) so other tests are unaffected.
    reconfigure_telemetry(Some(TelemetryConfig::default())).expect("restore must succeed");
}
