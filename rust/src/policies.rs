// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::BTreeMap;

use crate::backpressure::{set_queue_policy, QueuePolicy};
use crate::config::TelemetryConfig;
use crate::resilience::{set_exporter_policy, ExporterPolicy};
use crate::sampling::{set_sampling_policy, SamplingPolicy, Signal};
use crate::schema::set_strict_schema;

/// Apply sampling, backpressure, and exporter policies from a TelemetryConfig.
/// Called on initial setup and on every hot-reload.
pub(crate) fn apply_policies(config: &TelemetryConfig) {
    let _ = set_sampling_policy(
        Signal::Logs,
        SamplingPolicy {
            default_rate: config.sampling.logs_rate,
            overrides: BTreeMap::new(),
        },
    );
    let _ = set_sampling_policy(
        Signal::Traces,
        SamplingPolicy {
            default_rate: config.sampling.traces_rate.min(config.tracing.sample_rate),
            overrides: BTreeMap::new(),
        },
    );
    let _ = set_sampling_policy(
        Signal::Metrics,
        SamplingPolicy {
            default_rate: config.sampling.metrics_rate,
            overrides: BTreeMap::new(),
        },
    );
    set_queue_policy(QueuePolicy {
        logs_maxsize: config.backpressure.logs_maxsize,
        traces_maxsize: config.backpressure.traces_maxsize,
        metrics_maxsize: config.backpressure.metrics_maxsize,
    });
    let _ = set_exporter_policy(
        Signal::Logs,
        ExporterPolicy {
            retries: config.exporter.logs_retries as u32,
            backoff_seconds: config.exporter.logs_backoff_seconds,
            timeout_seconds: config.exporter.logs_timeout_seconds,
            fail_open: config.exporter.logs_fail_open,
            allow_blocking_in_event_loop: false,
        },
    );
    let _ = set_exporter_policy(
        Signal::Traces,
        ExporterPolicy {
            retries: config.exporter.traces_retries as u32,
            backoff_seconds: config.exporter.traces_backoff_seconds,
            timeout_seconds: config.exporter.traces_timeout_seconds,
            fail_open: config.exporter.traces_fail_open,
            allow_blocking_in_event_loop: false,
        },
    );
    let _ = set_exporter_policy(
        Signal::Metrics,
        ExporterPolicy {
            retries: config.exporter.metrics_retries as u32,
            backoff_seconds: config.exporter.metrics_backoff_seconds,
            timeout_seconds: config.exporter.metrics_timeout_seconds,
            fail_open: config.exporter.metrics_fail_open,
            allow_blocking_in_event_loop: false,
        },
    );
    // Sync the strict-schema atomic so event()/event_name()/enforce_schema()
    // see the same value as the runtime config snapshot.
    set_strict_schema(config.strict_schema || config.event_schema.strict_event_name);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::schema::get_strict_schema;
    use crate::testing::acquire_test_state_lock;

    #[test]
    fn policies_test_apply_policies_syncs_strict_schema_atomic() {
        // Acquire the global test-state lock so that apply_policies() calls to
        // set_exporter_policy() do not race with resilient-exporter tests that
        // set per-signal policies (e.g. fail_open=false).
        let _g = acquire_test_state_lock();
        // Verify that apply_policies propagates strict_schema from config
        // to the AtomicBool used by event()/event_name()/enforce_schema().
        let mut config = TelemetryConfig {
            strict_schema: true,
            ..TelemetryConfig::default()
        };
        apply_policies(&config);
        assert!(
            get_strict_schema(),
            "apply_policies must sync strict_schema=true to atomic"
        );

        config.strict_schema = false;
        apply_policies(&config);
        assert!(
            !get_strict_schema(),
            "apply_policies must sync strict_schema=false to atomic"
        );
    }
}
