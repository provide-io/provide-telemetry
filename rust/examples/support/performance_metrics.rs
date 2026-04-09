// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::time::Instant;

use provide_telemetry::{
    counter, event, gauge, histogram, setup_telemetry, should_sample, shutdown_telemetry, Signal,
    TelemetryError,
};

#[derive(Debug, Clone, PartialEq)]
pub struct DemoSummary {
    pub counter_ns: f64,
    pub event_ns: f64,
    pub should_sample_ns: f64,
}

fn bench(mut op: impl FnMut(), iterations: usize) -> f64 {
    let start = Instant::now();
    for _ in 0..iterations {
        op();
    }
    start.elapsed().as_nanos() as f64 / iterations as f64
}

pub fn run_demo() -> Result<DemoSummary, TelemetryError> {
    let _ = shutdown_telemetry();
    setup_telemetry()?;
    let c = counter("perf.example.requests", Some("bench counter"), None);
    let g = gauge("perf.example.active", Some("bench gauge"), None);
    let h = histogram("perf.example.latency", Some("bench histogram"), Some("ms"));

    let counter_ns = bench(
        || {
            c.add(1.0, None);
            g.set(42.0, None);
            h.record(3.14, None);
        },
        500,
    );
    let event_ns = bench(
        || {
            let _ = event(&["perf", "bench", "ok"]);
        },
        500,
    );
    let should_sample_ns = bench(
        || {
            let _ = should_sample(Signal::Logs, Some("perf.test"));
        },
        500,
    );
    shutdown_telemetry()?;
    Ok(DemoSummary {
        counter_ns,
        event_ns,
        should_sample_ns,
    })
}
