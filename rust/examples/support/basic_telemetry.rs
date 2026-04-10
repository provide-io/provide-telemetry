// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;

use provide_telemetry::context::get_context;
use provide_telemetry::{
    bind_context, clear_context, counter, event, gauge, get_logger, histogram, setup_telemetry,
    shutdown_telemetry, trace, unbind_context, Logger, TelemetryError,
};
use serde_json::json;

#[derive(Debug, Clone, PartialEq)]
pub struct DemoSummary {
    pub service_name: String,
    pub environment: String,
    pub version: String,
    pub iterations: usize,
    pub logged_events: usize,
    pub counter_total: f64,
    pub gauge_value: f64,
    pub histogram_count: usize,
    pub histogram_total: f64,
    pub context_keys_after_clear: usize,
    pub unbound_key: Option<String>,
}

fn telemetry_error(message: impl Into<String>) -> TelemetryError {
    TelemetryError::new(message)
}

pub fn run_demo() -> Result<DemoSummary, TelemetryError> {
    let _ = shutdown_telemetry();
    {
        let _clear = clear_context();
    }
    let _ = Logger::drain_events_for_tests();

    let config = setup_telemetry()?;
    let log = get_logger(Some("examples.basic"));
    let requests = counter(
        "example.basic.requests",
        Some("Total request count"),
        Some("request"),
    );
    let active_tasks = gauge(
        "example.basic.active_tasks",
        Some("Active task gauge"),
        Some("1"),
    );
    let latency = histogram(
        "example.basic.latency_ms",
        Some("Simulated latency"),
        Some("ms"),
    );

    let start =
        event(&["example", "basic", "start"]).map_err(|err| telemetry_error(err.message))?;
    let after_unbind =
        event(&["example", "basic", "after_unbind"]).map_err(|err| telemetry_error(err.message))?;
    let after_clear =
        event(&["example", "basic", "after_clear"]).map_err(|err| telemetry_error(err.message))?;

    let _bound = bind_context([
        ("region".to_string(), json!("us-east-1")),
        ("tier".to_string(), json!("premium")),
    ]);
    log.info(&start.event);

    for iteration in 0..3 {
        let iteration_event = event(&["example", "basic", "iteration"])
            .map_err(|err| telemetry_error(err.message))?;
        trace("example.basic.work", || {
            log.info(&iteration_event.event);

            let mut attributes = BTreeMap::new();
            attributes.insert("iteration".to_string(), iteration.to_string());
            requests.add(1.0, Some(attributes.clone()));
            latency.record(iteration as f64 * 12.5, Some(attributes));
            active_tasks.set(1.0, None);
        });
    }

    let _unbind = unbind_context(&["region"]);
    log.info(&after_unbind.event);

    let _clear = clear_context();
    log.info(&after_clear.event);

    let context_keys_after_clear = get_context().len();
    let logged_events = Logger::drain_events_for_tests().len();
    shutdown_telemetry()?;

    Ok(DemoSummary {
        service_name: config.service_name,
        environment: config.environment,
        version: config.version,
        iterations: 3,
        logged_events,
        counter_total: requests.value(),
        gauge_value: active_tasks.value(),
        histogram_count: latency.count(),
        histogram_total: latency.total(),
        context_keys_after_clear,
        unbound_key: Some("region".to_string()),
    })
}
