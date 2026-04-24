// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::sync::atomic::{AtomicU8, Ordering};

use provide_telemetry::{
    get_circuit_state, get_health_snapshot, run_with_resilience, set_exporter_policy,
    ExporterPolicy, Signal, TelemetryError,
};
use tokio::runtime::Builder;

#[derive(Debug, Clone, PartialEq)]
pub struct DemoSummary {
    pub fail_open_result_is_none: bool,
    pub fail_closed_is_error: bool,
    pub timeout_result_is_none: bool,
    pub metrics_circuit_state: String,
    pub metrics_open_count: u32,
    pub retries_logs: u64,
}

const DEMO_SUCCESS: u8 = 0;
const DEMO_ERROR: u8 = 1;
const DEMO_PENDING: u8 = 2;

static DEMO_OPERATION_MODE: AtomicU8 = AtomicU8::new(DEMO_SUCCESS);

fn set_demo_operation_mode(mode: u8) {
    DEMO_OPERATION_MODE.store(mode, Ordering::SeqCst);
}

async fn demo_operation() -> Result<(), TelemetryError> {
    match DEMO_OPERATION_MODE.load(Ordering::SeqCst) {
        DEMO_SUCCESS => Ok(()),
        DEMO_ERROR => Err(TelemetryError::new("exporter resilience demo failure")),
        DEMO_PENDING => std::future::pending::<Result<(), TelemetryError>>().await,
        _ => Err(TelemetryError::new("unknown exporter resilience demo mode")),
    }
}

pub fn run_demo() -> Result<DemoSummary, TelemetryError> {
    provide_telemetry::resilience::_reset_resilience_for_tests();
    provide_telemetry::health::_reset_health_for_tests();

    let runtime = Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|err| TelemetryError::new(format!("failed to build runtime: {err}")))?;

    let fail_open_result_is_none = runtime.block_on(async {
        set_exporter_policy(
            Signal::Logs,
            ExporterPolicy {
                retries: 1,
                backoff_seconds: 0.001,
                timeout_seconds: 0.0,
                fail_open: true,
                allow_blocking_in_event_loop: false,
            },
        )?;
        set_demo_operation_mode(DEMO_ERROR);
        let result: Option<()> = run_with_resilience(Signal::Logs, demo_operation).await?;
        Ok::<bool, TelemetryError>(result.is_none())
    })?;

    let fail_closed_is_error = runtime.block_on(async {
        set_exporter_policy(
            Signal::Logs,
            ExporterPolicy {
                retries: 1,
                backoff_seconds: 0.001,
                timeout_seconds: 0.0,
                fail_open: false,
                allow_blocking_in_event_loop: false,
            },
        )?;
        set_demo_operation_mode(DEMO_ERROR);
        Ok::<bool, TelemetryError>(
            run_with_resilience::<_, _, ()>(Signal::Logs, demo_operation)
                .await
                .is_err(),
        )
    })?;

    let timeout_result_is_none = runtime.block_on(async {
        set_exporter_policy(
            Signal::Traces,
            ExporterPolicy {
                retries: 0,
                backoff_seconds: 0.0,
                timeout_seconds: 0.05,
                fail_open: true,
                allow_blocking_in_event_loop: false,
            },
        )?;
        set_demo_operation_mode(DEMO_SUCCESS);
        let success: Option<()> = run_with_resilience(Signal::Traces, demo_operation).await?;
        if success != Some(()) {
            return Err(TelemetryError::new(
                "tracing resilience demo expected success before timeout path",
            ));
        }
        // future::pending() never resolves, so the wrapper timeout MUST fire.
        // Earlier `sleep(25ms) > timeout(10ms)` flaked on macOS-15 CI runners.
        set_demo_operation_mode(DEMO_PENDING);
        let result: Option<()> = run_with_resilience(Signal::Traces, demo_operation).await?;
        Ok::<bool, TelemetryError>(result.is_none())
    })?;

    runtime.block_on(async {
        set_exporter_policy(
            Signal::Metrics,
            ExporterPolicy {
                retries: 0,
                backoff_seconds: 0.0,
                timeout_seconds: 0.05,
                fail_open: true,
                allow_blocking_in_event_loop: false,
            },
        )?;
        set_demo_operation_mode(DEMO_PENDING);
        for _ in 0..4 {
            // Same pattern as above: pending future guarantees wrapper-imposed
            // timeout fires; only real timeouts count toward the circuit breaker.
            let _ = run_with_resilience::<_, _, ()>(Signal::Metrics, demo_operation).await?;
        }
        let short_circuit = run_with_resilience::<_, _, ()>(Signal::Metrics, demo_operation).await?;
        if short_circuit.is_some() {
            return Err(TelemetryError::new(
                "metrics resilience demo expected fail-open short circuit after breaker trip",
            ));
        }
        set_exporter_policy(
            Signal::Metrics,
            ExporterPolicy {
                retries: 0,
                backoff_seconds: 0.0,
                timeout_seconds: 0.05,
                fail_open: false,
                allow_blocking_in_event_loop: false,
            },
        )?;
        if run_with_resilience::<_, _, ()>(Signal::Metrics, demo_operation)
            .await
            .is_ok()
        {
            return Err(TelemetryError::new(
                "metrics resilience demo expected fail-closed short circuit after breaker trip",
            ));
        }
        Ok::<(), TelemetryError>(())
    })?;

    let (metrics_circuit_state, metrics_open_count, _) = get_circuit_state(Signal::Metrics)?;
    let snapshot = get_health_snapshot();

    Ok(DemoSummary {
        fail_open_result_is_none,
        fail_closed_is_error,
        timeout_result_is_none,
        metrics_circuit_state,
        metrics_open_count,
        retries_logs: snapshot.retries_logs,
    })
}
