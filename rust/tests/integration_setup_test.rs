// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// Setup / shutdown / provider-lifecycle integration tests. Split out of
// integration_test.rs so each file stays under the 500-LOC ceiling.

use std::sync::MutexGuard;

use provide_telemetry::testing::acquire_test_state_lock;
use provide_telemetry::Signal;

fn reset_policies() {
    provide_telemetry::sampling::_reset_sampling_for_tests();
    provide_telemetry::backpressure::_reset_backpressure_for_tests();
    provide_telemetry::resilience::_reset_resilience_for_tests();
    provide_telemetry::health::_reset_health_for_tests();
}

fn acquire_fresh_lock() -> MutexGuard<'static, ()> {
    let guard = acquire_test_state_lock();
    reset_policies();
    guard
}

#[cfg(feature = "otel")]
fn restore_var(key: &str, previous: Option<String>) {
    match previous {
        Some(value) => std::env::set_var(key, value),
        None => std::env::remove_var(key),
    }
}

#[cfg(feature = "otel")]
fn reset_runtime() {
    use provide_telemetry::shutdown_telemetry;

    let _ = shutdown_telemetry();
    provide_telemetry::otel::_reset_otel_for_tests();
}

#[cfg(feature = "otel")]
#[test]
fn integration_test_setup_registers_otel_providers() {
    use provide_telemetry::setup_telemetry;

    let _guard = acquire_fresh_lock();
    reset_runtime();

    let endpoint_key = "OTEL_EXPORTER_OTLP_ENDPOINT";
    let previous_endpoint = std::env::var(endpoint_key).ok();
    std::env::set_var(endpoint_key, "http://127.0.0.1:1/never");
    std::env::set_var("PROVIDE_TELEMETRY_SERVICE_NAME", "rust-otel-test");
    let config = setup_telemetry().expect("setup should succeed");

    assert_eq!(config.service_name, "rust-otel-test");
    assert!(provide_telemetry::otel::otel_installed_for_tests());

    reset_runtime();
    restore_var(endpoint_key, previous_endpoint);
    std::env::remove_var("PROVIDE_TELEMETRY_SERVICE_NAME");
}

#[cfg(feature = "otel")]
#[test]
fn integration_test_reconfigure_rejects_provider_replacement_after_install() {
    use provide_telemetry::{get_runtime_config, reconfigure_telemetry, setup_telemetry};

    let _guard = acquire_fresh_lock();
    reset_runtime();

    let endpoint_key = "OTEL_EXPORTER_OTLP_ENDPOINT";
    let previous_endpoint = std::env::var(endpoint_key).ok();
    std::env::set_var(endpoint_key, "http://127.0.0.1:1/never");
    std::env::set_var("PROVIDE_TELEMETRY_SERVICE_NAME", "rust-otel-test");
    setup_telemetry().expect("setup should succeed");

    let mut changed = get_runtime_config().expect("runtime config should exist");
    changed.service_name = "rust-otel-test-2".to_string();
    let err = reconfigure_telemetry(Some(changed)).expect_err("provider replacement should fail");
    assert!(err
        .to_string()
        .contains("OpenTelemetry providers already installed"));

    reset_runtime();
    restore_var(endpoint_key, previous_endpoint);
    std::env::remove_var("PROVIDE_TELEMETRY_SERVICE_NAME");
}

#[cfg(feature = "otel")]
#[test]
fn integration_test_shutdown_then_setup_reinstalls_otel_providers() {
    use provide_telemetry::{otel::otel_installed_for_tests, setup_telemetry, shutdown_telemetry};

    let _guard = acquire_fresh_lock();
    reset_runtime();

    let endpoint_key = "OTEL_EXPORTER_OTLP_ENDPOINT";
    let previous_endpoint = std::env::var(endpoint_key).ok();
    std::env::set_var(endpoint_key, "http://127.0.0.1:1/never");
    setup_telemetry().expect("first setup should succeed");
    assert!(
        otel_installed_for_tests(),
        "otel should be marked installed after setup"
    );

    shutdown_telemetry().expect("shutdown should succeed");
    assert!(
        !otel_installed_for_tests(),
        "otel should be marked uninstalled after shutdown"
    );

    setup_telemetry().expect("second setup should succeed");
    assert!(
        otel_installed_for_tests(),
        "otel should be reinstalled after shutdown + setup"
    );

    reset_runtime();
    restore_var(endpoint_key, previous_endpoint);
}

#[cfg(feature = "otel")]
#[test]
fn integration_test_installed_meter_provider_exercises_gauge_add_otel_path() {
    use provide_telemetry::{gauge, setup_telemetry};

    let _guard = acquire_fresh_lock();
    reset_runtime();

    let endpoint_key = "OTEL_EXPORTER_OTLP_ENDPOINT";
    let previous_endpoint = std::env::var(endpoint_key).ok();
    std::env::set_var(endpoint_key, "http://127.0.0.1:1/never");

    setup_telemetry().expect("setup should succeed");
    let metric = gauge("integration.gauge", None, None);
    metric.add(2.0, None);

    assert_eq!(metric.value(), 2.0);

    reset_runtime();
    restore_var(endpoint_key, previous_endpoint);
}

#[cfg(feature = "otel")]
#[test]
fn integration_test_fail_open_setup_does_not_mark_otel_installed_without_providers() {
    use provide_telemetry::{otel::otel_installed_for_tests, setup_telemetry};

    let _guard = acquire_fresh_lock();
    reset_runtime();

    let endpoint_key = "OTEL_EXPORTER_OTLP_ENDPOINT";
    let protocol_key = "OTEL_EXPORTER_OTLP_PROTOCOL";
    let previous_endpoint = std::env::var(endpoint_key).ok();
    let previous_protocol = std::env::var(protocol_key).ok();
    std::env::set_var(endpoint_key, "http://127.0.0.1:1/never");
    std::env::set_var(protocol_key, "definitely-invalid");

    setup_telemetry().expect("setup should degrade successfully under fail_open");
    assert!(
        !otel_installed_for_tests(),
        "otel should remain uninstalled when all provider builds fail open"
    );

    restore_var(endpoint_key, previous_endpoint);
    restore_var(protocol_key, previous_protocol);
    reset_runtime();
}

#[test]
fn setup_test_sampling_policy_applied_from_config() {
    use provide_telemetry::{get_sampling_policy, setup_telemetry, shutdown_telemetry};

    let _guard = acquire_fresh_lock();
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
