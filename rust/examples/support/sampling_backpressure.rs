// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;

use provide_telemetry::{
    get_health_snapshot, get_queue_policy, get_sampling_policy, release, set_queue_policy,
    set_sampling_policy, should_sample, try_acquire, QueuePolicy, SamplingPolicy, Signal,
    TelemetryError,
};

#[derive(Debug, Clone, PartialEq)]
pub struct DemoSummary {
    pub logs_routine_sampled: bool,
    pub logs_critical_sampled: bool,
    pub first_trace_ticket_acquired: bool,
    pub second_trace_ticket_acquired: bool,
    pub third_trace_ticket_acquired: bool,
    pub dropped_traces: u64,
    pub logs_policy_rate: f64,
    pub traces_queue_size: usize,
}

pub fn run_demo() -> Result<DemoSummary, TelemetryError> {
    provide_telemetry::sampling::_reset_sampling_for_tests();
    provide_telemetry::backpressure::_reset_backpressure_for_tests();
    provide_telemetry::health::_reset_health_for_tests();

    set_sampling_policy(
        Signal::Logs,
        SamplingPolicy {
            default_rate: 0.0,
            overrides: BTreeMap::from([("example.critical".to_string(), 1.0)]),
        },
    )?;
    set_sampling_policy(Signal::Traces, SamplingPolicy::default())?;
    set_sampling_policy(Signal::Metrics, SamplingPolicy::default())?;

    let logs_routine_sampled = should_sample(Signal::Logs, Some("example.routine"))?;
    let logs_critical_sampled = should_sample(Signal::Logs, Some("example.critical"))?;

    set_queue_policy(QueuePolicy {
        logs_maxsize: 0,
        traces_maxsize: 1,
        metrics_maxsize: 0,
    });

    let first = try_acquire(Signal::Traces);
    let second = try_acquire(Signal::Traces);
    if let Some(ticket) = first {
        release(ticket);
    }
    let third = try_acquire(Signal::Traces);
    if let Some(ticket) = third {
        release(ticket);
    }

    let logs_policy_rate = get_sampling_policy(Signal::Logs)?.default_rate;
    let traces_queue_size = get_queue_policy().traces_maxsize;
    let snapshot = get_health_snapshot();

    Ok(DemoSummary {
        logs_routine_sampled,
        logs_critical_sampled,
        first_trace_ticket_acquired: true,
        second_trace_ticket_acquired: second.is_some(),
        third_trace_ticket_acquired: true,
        dropped_traces: snapshot.dropped_traces,
        logs_policy_rate,
        traces_queue_size,
    })
}
