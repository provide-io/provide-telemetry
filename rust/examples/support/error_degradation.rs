// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::HashMap;

use provide_telemetry::{
    event, set_strict_schema, setup_telemetry, shutdown_telemetry, ConfigurationError,
    EventSchemaError, TelemetryConfig, TelemetryError,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DemoSummary {
    pub configuration_error_seen: bool,
    pub event_schema_error_seen: bool,
    pub telemetry_error_catchall_count: usize,
}

pub fn run_demo() -> Result<DemoSummary, TelemetryError> {
    let _ = shutdown_telemetry();
    setup_telemetry()?;

    let bad_bool = TelemetryConfig::from_map(&HashMap::from([(
        "PROVIDE_TRACE_ENABLED".to_string(),
        "not-bool".to_string(),
    )]));
    let configuration_error_seen = matches!(bad_bool, Err(ConfigurationError { .. }));

    // Strict schema mode is required to surface segment-format errors from event().
    set_strict_schema(true);
    let bad_event = event(&["BAD", "UPPER", "case"]);
    let event_schema_error_seen = matches!(bad_event, Err(EventSchemaError { .. }));

    let mut telemetry_error_catchall_count = 0;
    for segments in [
        vec!["x"],
        vec!["A", "B", "C"],
        vec!["a", "b", "c", "d", "e"],
    ] {
        if let Err(_err) = event(&segments) {
            telemetry_error_catchall_count += 1;
        }
    }
    set_strict_schema(false);

    shutdown_telemetry()?;
    Ok(DemoSummary {
        configuration_error_seen,
        event_schema_error_seen,
        telemetry_error_catchall_count,
    })
}
