// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use std::sync::{Mutex, OnceLock};
use std::time::Duration;

use tokio::runtime::Builder;

use provide_telemetry::{
    get_circuit_state, get_health_snapshot, release, run_with_resilience, set_exporter_policy,
    set_queue_policy, set_sampling_policy, should_sample, try_acquire, ExporterPolicy, QueuePolicy,
    SamplingPolicy, Signal,
};

static POLICY_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn policy_lock() -> &'static Mutex<()> {
    POLICY_LOCK.get_or_init(|| Mutex::new(()))
}

fn reset_policies() {
    provide_telemetry::sampling::_reset_sampling_for_tests();
    provide_telemetry::backpressure::_reset_backpressure_for_tests();
    provide_telemetry::resilience::_reset_resilience_for_tests();
    provide_telemetry::health::_reset_health_for_tests();
}

#[cfg(feature = "otel")]
fn reset_runtime() {
    use provide_telemetry::shutdown_telemetry;

    let _ = shutdown_telemetry();
    provide_telemetry::otel::_reset_otel_for_tests();
}

#[test]
fn integration_test_sampling_drop_increments_health() {
    let _guard = policy_lock().lock().expect("policy lock poisoned");
    reset_policies();
    set_sampling_policy(
        Signal::Logs,
        SamplingPolicy {
            default_rate: 0.0,
            overrides: Default::default(),
        },
    )
    .expect("policy should set");

    let keep = should_sample(Signal::Logs, Some("event-name")).expect("sampling should work");
    assert!(!keep);

    let snapshot = get_health_snapshot();
    assert_eq!(snapshot.dropped_logs, 1);
}

#[test]
fn integration_test_bounded_queue_drop_increments_health() {
    let _guard = policy_lock().lock().expect("policy lock poisoned");
    reset_policies();
    set_queue_policy(QueuePolicy {
        logs_maxsize: 1,
        traces_maxsize: 0,
        metrics_maxsize: 0,
    });

    let ticket = try_acquire(Signal::Logs).expect("first acquire should succeed");
    let dropped = try_acquire(Signal::Logs);
    assert!(dropped.is_none());

    let snapshot = get_health_snapshot();
    assert_eq!(snapshot.dropped_logs, 1);

    release(ticket);
}

#[test]
fn integration_test_circuit_breaker_trips_after_three_timeouts() {
    let _guard = policy_lock().lock().expect("policy lock poisoned");
    reset_policies();
    let runtime = Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime");

    runtime.block_on(async {
        set_exporter_policy(
            Signal::Logs,
            ExporterPolicy {
                retries: 0,
                backoff_seconds: 0.0,
                timeout_seconds: 0.01,
                fail_open: true,
                allow_blocking_in_event_loop: false,
            },
        )
        .expect("policy should set");

        for _ in 0..3 {
            let result = run_with_resilience(Signal::Logs, async {
                tokio::time::sleep(Duration::from_millis(25)).await;
                Ok::<_, provide_telemetry::TelemetryError>(())
            })
            .await
            .expect("timeout should be fail-open");
            assert!(result.is_none());
        }

        let state = get_circuit_state(Signal::Logs).expect("state should be available");
        assert_eq!(state.0, "open");

        let short_circuit = run_with_resilience(Signal::Logs, async {
            Ok::<_, provide_telemetry::TelemetryError>(())
        })
        .await
        .expect("open circuit should fail open");
        assert!(short_circuit.is_none());
    });

    let snapshot = get_health_snapshot();
    assert!(snapshot.export_failures_logs >= 3);
    assert!(snapshot.circuit_open_count_logs >= 1);
    assert_eq!(snapshot.circuit_state_logs, "open");
}

#[cfg(feature = "otel")]
#[test]
fn integration_test_setup_registers_otel_providers() {
    use provide_telemetry::setup_telemetry;

    let _guard = policy_lock().lock().expect("policy lock poisoned");
    reset_runtime();

    std::env::set_var("PROVIDE_TELEMETRY_SERVICE_NAME", "rust-otel-test");
    let config = setup_telemetry().expect("setup should succeed");

    assert_eq!(config.service_name, "rust-otel-test");
    assert!(provide_telemetry::otel::otel_installed_for_tests());

    reset_runtime();
    std::env::remove_var("PROVIDE_TELEMETRY_SERVICE_NAME");
}

#[cfg(feature = "otel")]
#[test]
fn integration_test_reconfigure_rejects_provider_replacement_after_install() {
    use provide_telemetry::{get_runtime_config, reconfigure_telemetry, setup_telemetry};

    let _guard = policy_lock().lock().expect("policy lock poisoned");
    reset_runtime();

    std::env::set_var("PROVIDE_TELEMETRY_SERVICE_NAME", "rust-otel-test");
    setup_telemetry().expect("setup should succeed");

    let mut changed = get_runtime_config().expect("runtime config should exist");
    changed.service_name = "rust-otel-test-2".to_string();
    let err = reconfigure_telemetry(Some(changed)).expect_err("provider replacement should fail");
    assert!(err
        .to_string()
        .contains("OpenTelemetry providers already installed"));

    reset_runtime();
    std::env::remove_var("PROVIDE_TELEMETRY_SERVICE_NAME");
}
