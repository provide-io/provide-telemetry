// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#![cfg(feature = "otel")]

#[path = "../examples/support/openobserve_shared.rs"]
mod openobserve_shared;

#[test]
fn openobserve_test_auth_header_uses_basic_auth() {
    let header = openobserve_shared::auth_header("admin@provide.test", "Complexpass#123");
    assert!(header.starts_with("Basic "));
}

#[test]
fn openobserve_test_endpoints_match_openobserve_layout() {
    let endpoints = openobserve_shared::OpenObserveEndpoints::new("http://localhost:5080/api/default");

    assert_eq!(endpoints.traces, "http://localhost:5080/api/default/v1/traces");
    assert_eq!(endpoints.metrics, "http://localhost:5080/api/default/v1/metrics");
    assert_eq!(endpoints.logs, "http://localhost:5080/api/default/v1/logs");
    assert_eq!(endpoints.json_logs, "http://localhost:5080/api/default/default/_json");
}

#[test]
fn openobserve_test_otlp_providers_build_with_http_exporters() {
    let endpoints = openobserve_shared::OpenObserveEndpoints::new("http://localhost:5080/api/default");
    let auth = openobserve_shared::auth_header("admin@provide.test", "Complexpass#123");

    let tracer = openobserve_shared::build_tracer_provider(&endpoints, &auth, "rust-openobserve-test");
    let logger = openobserve_shared::build_logger_provider(&endpoints, &auth, "rust-openobserve-test");
    let meter = openobserve_shared::build_meter_provider(&endpoints, &auth, "rust-openobserve-test");

    assert!(tracer.is_ok(), "tracer provider should build: {tracer:?}");
    assert!(logger.is_ok(), "logger provider should build: {logger:?}");
    assert!(meter.is_ok(), "meter provider should build: {meter:?}");
}
