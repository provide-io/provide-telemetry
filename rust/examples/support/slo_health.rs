// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use provide_telemetry::{classify_error, get_health_snapshot, TelemetryError};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DemoSummary {
    pub classify_404: Option<String>,
    pub classify_503: Option<String>,
    pub classify_200: Option<String>,
    pub dropped_logs: u64,
}

pub fn run_demo() -> Result<DemoSummary, TelemetryError> {
    provide_telemetry::health::_reset_health_for_tests();
    let snapshot = get_health_snapshot();
    Ok(DemoSummary {
        classify_404: Some(classify_error(404)),
        classify_503: Some(classify_error(503)),
        classify_200: Some(classify_error(200)),
        dropped_logs: snapshot.dropped_logs,
    })
}
