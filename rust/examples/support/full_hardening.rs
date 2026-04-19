// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use provide_telemetry::{
    get_cardinality_limits, get_circuit_state, get_queue_policy, register_cardinality_limit,
    register_pii_rule, run_with_resilience, set_exporter_policy, set_queue_policy,
    set_sampling_policy, CardinalityLimit, ExporterPolicy, PIIMode, PIIRule, QueuePolicy,
    SamplingPolicy, Signal, TelemetryError,
};
use tokio::runtime::Builder;

#[derive(Debug, Clone, PartialEq)]
pub struct DemoSummary {
    pub pii_rules_active: usize,
    pub cardinality_limit_max: Option<usize>,
    pub queue_traces_maxsize: usize,
    pub metrics_circuit_state: String,
}

pub fn run_demo() -> Result<DemoSummary, TelemetryError> {
    provide_telemetry::sampling::_reset_sampling_for_tests();
    provide_telemetry::backpressure::_reset_backpressure_for_tests();
    provide_telemetry::resilience::_reset_resilience_for_tests();
    provide_telemetry::pii::replace_pii_rules(Vec::new());
    provide_telemetry::clear_cardinality_limits();

    register_pii_rule(PIIRule::new(
        vec!["user".into(), "email".into()],
        PIIMode::Hash,
        0,
    ));
    register_pii_rule(PIIRule::new(vec!["credit_card".into()], PIIMode::Drop, 0));
    register_cardinality_limit(
        "player_id",
        CardinalityLimit {
            max_values: 3,
            ttl_seconds: 300.0,
        },
    );
    set_sampling_policy(
        Signal::Logs,
        SamplingPolicy {
            default_rate: 0.5,
            overrides: Default::default(),
        },
    )?;
    set_queue_policy(QueuePolicy {
        logs_maxsize: 0,
        traces_maxsize: 2,
        metrics_maxsize: 0,
    });
    set_exporter_policy(
        Signal::Metrics,
        ExporterPolicy {
            retries: 2,
            backoff_seconds: 0.01,
            // Short timeout so the wrapper-imposed deadline fires below.
            timeout_seconds: 0.01,
            fail_open: true,
            allow_blocking_in_event_loop: false,
        },
    )?;

    let runtime = Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|err| TelemetryError::new(format!("failed to build runtime: {err}")))?;
    runtime.block_on(async {
        for _ in 0..4 {
            // Sleep longer than timeout_seconds so tokio::time::timeout fires;
            // only real timeouts count toward the circuit breaker.
            let _: Option<()> = run_with_resilience(Signal::Metrics, || async {
                tokio::time::sleep(std::time::Duration::from_millis(50)).await;
                Ok(())
            })
            .await?;
        }
        Ok::<(), TelemetryError>(())
    })?;

    let queue = get_queue_policy();
    let limits = get_cardinality_limits();
    let (state, _, _) = get_circuit_state(Signal::Metrics)?;

    Ok(DemoSummary {
        pii_rules_active: provide_telemetry::get_pii_rules().len(),
        cardinality_limit_max: limits.get("player_id").map(|limit| limit.max_values),
        queue_traces_maxsize: queue.traces_maxsize,
        metrics_circuit_state: state,
    })
}
