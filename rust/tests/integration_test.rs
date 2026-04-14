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

#[cfg(feature = "otel")]
#[path = "../examples/support/e2e_shared.rs"]
mod e2e_shared;

#[path = "../examples/support/basic_telemetry.rs"]
mod basic_telemetry;
#[cfg(feature = "governance")]
#[path = "../examples/support/data_governance.rs"]
mod data_governance;
#[path = "../examples/support/error_degradation.rs"]
mod error_degradation;
#[path = "../examples/support/error_sessions.rs"]
mod error_sessions;
#[path = "../examples/support/exporter_resilience.rs"]
mod exporter_resilience;
#[path = "../examples/support/full_hardening.rs"]
mod full_hardening;
#[path = "../examples/support/lazy_loading.rs"]
mod lazy_loading;
#[path = "../examples/support/performance_metrics.rs"]
mod performance_metrics;
#[path = "../examples/support/pii_cardinality.rs"]
mod pii_cardinality;
#[path = "../examples/support/runtime_reconfigure.rs"]
mod runtime_reconfigure;
#[path = "../examples/support/sampling_backpressure.rs"]
mod sampling_backpressure;
#[path = "../examples/support/security_hardening.rs"]
mod security_hardening;
#[path = "../examples/support/slo_health.rs"]
mod slo_health;
#[path = "../examples/support/w3c_propagation.rs"]
mod w3c_propagation;

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
fn restore_var(key: &str, previous: Option<String>) {
    match previous {
        Some(value) => std::env::set_var(key, value),
        None => std::env::remove_var(key),
    }
}

#[cfg(feature = "otel")]
#[test]
fn integration_test_e2e_tracer_provider_builds_with_http_exporter() {
    let endpoint_key = "OTEL_EXPORTER_OTLP_ENDPOINT";
    let headers_key = "OTEL_EXPORTER_OTLP_HEADERS";
    let previous_endpoint = std::env::var(endpoint_key).ok();
    let previous_headers = std::env::var(headers_key).ok();
    std::env::set_var(endpoint_key, "http://localhost:5080/api/default");
    std::env::set_var(headers_key, "Authorization=Basic%20test");

    let result = e2e_shared::init_tracer_provider("rust-e2e-test");

    restore_var(endpoint_key, previous_endpoint);
    restore_var(headers_key, previous_headers);

    assert!(
        result.is_ok(),
        "expected OTLP tracer provider to build for E2E helper, got {result:?}"
    );
}

#[test]
fn integration_test_basic_example_summary_matches_demo_flow() {
    let _guard = policy_lock().lock().expect("policy lock poisoned");
    let summary = basic_telemetry::run_demo().expect("basic telemetry example should succeed");

    assert_eq!(summary.iterations, 3);
    assert_eq!(summary.logged_events, 6);
    assert_eq!(summary.counter_total, 3.0);
    assert_eq!(summary.gauge_value, 1.0);
    assert_eq!(summary.histogram_count, 3);
    assert_eq!(summary.histogram_total, 37.5);
    assert_eq!(summary.context_keys_after_clear, 0);
    assert_eq!(summary.unbound_key.as_deref(), Some("region"));
}

#[test]
fn integration_test_w3c_example_summary_matches_demo_flow() {
    let _guard = policy_lock().lock().expect("policy lock poisoned");
    let summary = w3c_propagation::run_demo().expect("w3c propagation example should succeed");

    assert_eq!(
        summary.http_trace_id.as_deref(),
        Some("4bf92f3577b34da6a3ce929d0e0e4736") // pragma: allowlist secret
    );
    assert_eq!(summary.manual_trace_id_after_clear, None);
    assert_eq!(
        summary.nested_outer_restored.as_deref(),
        Some("1111111111111111ffffffffffffffff")
    );
    assert_eq!(summary.nested_after_clear, None);
}

#[test]
fn integration_test_sampling_example_summary_matches_demo_flow() {
    let _guard = policy_lock().lock().expect("policy lock poisoned");
    let summary = sampling_backpressure::run_demo().expect("sampling example should succeed");

    assert!(!summary.logs_routine_sampled);
    assert!(summary.logs_critical_sampled);
    assert!(summary.first_trace_ticket_acquired);
    assert!(!summary.second_trace_ticket_acquired);
    assert!(summary.third_trace_ticket_acquired);
    assert!(summary.dropped_traces >= 1);
}

#[test]
fn integration_test_runtime_example_summary_matches_demo_flow() {
    let _guard = policy_lock().lock().expect("policy lock poisoned");
    let summary = runtime_reconfigure::run_demo().expect("runtime example should succeed");

    assert_eq!(summary.before_logs_rate, 1.0);
    assert_eq!(summary.after_update_logs_rate, 0.0);
    assert_eq!(summary.after_reconfigure_logs_rate, 1.0);
    assert_eq!(summary.after_reload_logs_rate, 1.0);
}

#[test]
fn integration_test_pii_example_summary_matches_demo_flow() {
    let _guard = policy_lock().lock().expect("policy lock poisoned");
    let summary = pii_cardinality::run_demo().expect("pii/cardinality example should succeed");

    assert_eq!(summary.hashed_email_len, 12);
    assert!(summary.credit_card_removed);
    assert_eq!(summary.truncated_password.as_deref(), Some("hunt..."));
    assert_eq!(summary.cardinality_max_values, Some(1));
    assert_eq!(summary.cardinality_ttl_seconds, Some(1.0));
}

#[test]
fn integration_test_resilience_example_summary_matches_demo_flow() {
    let _guard = policy_lock().lock().expect("policy lock poisoned");
    let summary = exporter_resilience::run_demo().expect("resilience example should succeed");

    assert!(summary.fail_open_result_is_none);
    assert!(summary.fail_closed_is_error);
    assert!(summary.timeout_result_is_none);
    assert_eq!(summary.metrics_circuit_state.as_str(), "open");
    assert!(summary.metrics_open_count >= 1);
}

#[test]
fn integration_test_slo_example_summary_matches_demo_flow() {
    let _guard = policy_lock().lock().expect("policy lock poisoned");
    let summary = slo_health::run_demo().expect("slo example should succeed");

    assert_eq!(summary.classify_404.as_deref(), Some("client_error"));
    assert_eq!(summary.classify_503.as_deref(), Some("server_error"));
    assert_eq!(summary.classify_200.as_deref(), Some("ok"));
}

#[test]
fn integration_test_full_hardening_example_summary_matches_demo_flow() {
    let _guard = policy_lock().lock().expect("policy lock poisoned");
    let summary = full_hardening::run_demo().expect("hardening example should succeed");

    assert_eq!(summary.pii_rules_active, 2);
    assert_eq!(summary.cardinality_limit_max, Some(3));
    assert_eq!(summary.queue_traces_maxsize, 2);
    assert_eq!(summary.metrics_circuit_state.as_str(), "open");
}

#[test]
fn integration_test_error_degradation_example_summary_matches_demo_flow() {
    let _guard = policy_lock().lock().expect("policy lock poisoned");
    let summary = error_degradation::run_demo().expect("error/degradation example should succeed");

    assert!(summary.configuration_error_seen);
    assert!(summary.event_schema_error_seen);
    assert!(summary.telemetry_error_catchall_count >= 2);
}

#[test]
fn integration_test_performance_example_summary_matches_demo_flow() {
    let _guard = policy_lock().lock().expect("policy lock poisoned");
    let summary = performance_metrics::run_demo().expect("performance example should succeed");

    assert!(summary.event_ns > 0.0);
    assert!(summary.counter_ns > 0.0);
    assert!(summary.should_sample_ns > 0.0);
}

#[test]
fn integration_test_lazy_loading_example_summary_matches_demo_flow() {
    let _guard = policy_lock().lock().expect("policy lock poisoned");
    let summary = lazy_loading::run_demo().expect("lazy loading example should succeed");

    assert!(!summary.slo_loaded_before_classify);
    assert!(!summary.metrics_loaded_before_use);
    assert!(summary.slo_loaded_after_classify);
    assert!(summary.metrics_loaded_after_use);
}

#[test]
fn integration_test_error_sessions_example_summary_matches_demo_flow() {
    let _guard = policy_lock().lock().expect("policy lock poisoned");
    let summary = error_sessions::run_demo().expect("error/session example should succeed");

    assert_eq!(summary.value_error_a, summary.value_error_b);
    assert_ne!(summary.value_error_a, summary.type_error);
    assert!(!summary.runtime_error_fingerprint.is_empty());
    assert_eq!(summary.session_before, None);
    assert_eq!(summary.session_after_bind.as_deref(), Some("sess-demo-42"));
    assert_eq!(summary.session_after_clear, None);
}

#[test]
fn integration_test_security_hardening_example_summary_matches_demo_flow() {
    let _guard = policy_lock().lock().expect("policy lock poisoned");
    let summary = security_hardening::run_demo().expect("security example should succeed");

    assert!(summary.secret_redacted);
    assert!(summary.password_redacted);
    assert_eq!(summary.depth_preserved_leaf.as_deref(), Some("deep"));
}

#[cfg(feature = "governance")]
#[test]
fn integration_test_data_governance_example_summary_matches_demo_flow() {
    let _guard = policy_lock().lock().expect("policy lock poisoned");
    let summary = data_governance::run_demo().expect("data governance example should succeed");

    assert!(summary.full_logs_debug_allowed);
    assert!(!summary.none_traces_allowed);
    assert_eq!(summary.redacted_ssn.as_deref(), Some("***"));
    assert_eq!(summary.hashed_card_len, Some(12));
    assert!(summary.diagnosis_dropped);
    assert!(summary.api_key_dropped);
    assert_eq!(summary.ssn_class.as_deref(), Some("PII"));
    assert_eq!(summary.card_class.as_deref(), Some("PCI"));
    assert_eq!(summary.receipt_action.as_deref(), Some("redact"));
    assert!(summary.receipt_hmac_prefix_len >= 8);
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
    let reacquired = try_acquire(Signal::Logs);
    assert!(
        reacquired.is_some(),
        "release should restore queue capacity"
    );
    if let Some(ticket) = reacquired {
        release(ticket);
    }
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
            let result = run_with_resilience(Signal::Logs, || async {
                tokio::time::sleep(Duration::from_millis(25)).await;
                Ok::<_, provide_telemetry::TelemetryError>(())
            })
            .await
            .expect("timeout should be fail-open");
            assert!(result.is_none());
        }

        let state = get_circuit_state(Signal::Logs).expect("state should be available");
        assert_eq!(state.0, "open");

        let short_circuit = run_with_resilience(Signal::Logs, || async {
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

#[test]
fn setup_test_sampling_policy_applied_from_config() {
    use provide_telemetry::{get_sampling_policy, setup_telemetry, shutdown_telemetry};

    let _guard = policy_lock().lock().expect("policy lock poisoned");
    reset_policies();
    let _ = shutdown_telemetry();

    std::env::set_var("PROVIDE_SAMPLING_LOGS_RATE", "0.25");
    std::env::set_var("PROVIDE_SAMPLING_TRACES_RATE", "0.5");

    let _ = setup_telemetry();

    let logs_policy = get_sampling_policy(Signal::Logs).expect("logs policy should exist");
    assert!(
        (logs_policy.default_rate - 0.25).abs() < 1e-9,
        "expected logs rate 0.25, got {}",
        logs_policy.default_rate
    );

    let traces_policy = get_sampling_policy(Signal::Traces).expect("traces policy should exist");
    assert!(
        (traces_policy.default_rate - 0.5).abs() < 1e-9,
        "expected traces rate 0.5, got {}",
        traces_policy.default_rate
    );

    let _ = shutdown_telemetry();
    std::env::remove_var("PROVIDE_SAMPLING_LOGS_RATE");
    std::env::remove_var("PROVIDE_SAMPLING_TRACES_RATE");
    reset_policies();
}
