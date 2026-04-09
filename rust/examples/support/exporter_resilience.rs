// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::time::Duration;

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
                backoff_seconds: 0.0,
                timeout_seconds: 0.0,
                fail_open: true,
                allow_blocking_in_event_loop: false,
            },
        )?;
        let result: Option<()> = run_with_resilience(Signal::Logs, async {
            Err(TelemetryError::new("fail-open"))
        })
        .await?;
        Ok::<bool, TelemetryError>(result.is_none())
    })?;

    let fail_closed_is_error = runtime.block_on(async {
        set_exporter_policy(
            Signal::Logs,
            ExporterPolicy {
                retries: 1,
                backoff_seconds: 0.0,
                timeout_seconds: 0.0,
                fail_open: false,
                allow_blocking_in_event_loop: false,
            },
        )?;
        Ok::<bool, TelemetryError>(
            run_with_resilience::<_, ()>(Signal::Logs, async {
                Err(TelemetryError::new("fail-closed"))
            })
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
                timeout_seconds: 0.01,
                fail_open: true,
                allow_blocking_in_event_loop: false,
            },
        )?;
        let result: Option<()> = run_with_resilience(Signal::Traces, async {
            tokio::time::sleep(Duration::from_millis(25)).await;
            Ok(())
        })
        .await?;
        Ok::<bool, TelemetryError>(result.is_none())
    })?;

    runtime.block_on(async {
        set_exporter_policy(
            Signal::Metrics,
            ExporterPolicy {
                retries: 0,
                backoff_seconds: 0.0,
                timeout_seconds: 0.01,
                fail_open: true,
                allow_blocking_in_event_loop: false,
            },
        )?;
        for _ in 0..4 {
            let _ = run_with_resilience::<_, ()>(Signal::Metrics, async {
                Err(TelemetryError::new("timeout"))
            })
            .await?;
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
