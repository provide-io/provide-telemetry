// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use provide_telemetry::{counter, gauge, histogram};

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
