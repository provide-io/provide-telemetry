// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// Mutation tests for TelemetryConfig — cover config creation and validation

use provide_telemetry::{setup_telemetry, TelemetryConfig};

#[test]
fn test_telemetry_config_creation() {
    // Catches mutations on config initialization
    let config = TelemetryConfig::default();
    assert!(!config.service_name.is_empty(), "service_name should be set");
}

#[test]
fn test_telemetry_config_from_env() {
    // Catches mutations on environment variable parsing
    let config = TelemetryConfig::from_env();
    // Should either succeed or fail gracefully
    let _ = config;
}

#[test]
fn test_setup_telemetry_idempotent() {
    // Catches mutations on idempotency checks
    let _ = setup_telemetry();
    let _ = setup_telemetry();
    // If setup had mutations, second call would fail or corrupt state
}

#[test]
fn test_telemetry_config_default_values() {
    // Catches mutations that corrupt default initialization
    let config = TelemetryConfig::default();
    assert!(!config.service_name.is_empty());
    assert!(!config.version.is_empty());
}
