// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// Mutation tests for config.rs

use provide_telemetry::{TelemetryConfig, setup_telemetry};

#[test]
fn test_telemetry_config_default() {
    let config = TelemetryConfig::default();
    assert!(!config.service_name.is_empty());
}

#[test]
fn test_telemetry_config_from_env() {
    let _config = TelemetryConfig::from_env();
}

#[test]
fn test_setup_telemetry() {
    let _ = setup_telemetry();
    let _ = setup_telemetry();
}
