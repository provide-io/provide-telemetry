// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use provide_telemetry::{
    classify_error, counter, reset_metrics_for_tests, reset_slo_for_tests, TelemetryError,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DemoSummary {
    pub slo_loaded_before_classify: bool,
    pub metrics_loaded_before_use: bool,
    pub slo_loaded_after_classify: bool,
    pub metrics_loaded_after_use: bool,
}

pub fn run_demo() -> Result<DemoSummary, TelemetryError> {
    reset_slo_for_tests();
    reset_metrics_for_tests();

    let slo_loaded_before_classify = provide_telemetry::slo::slo_initialized_for_tests();
    let metrics_loaded_before_use = provide_telemetry::metrics::metrics_initialized_for_tests();

    let _ = classify_error("InternalError", Some(503));
    let request_counter = counter("example.lazy.requests", Some("Lazy init proof"), Some("1"));
    request_counter.add(1.0, None);

    Ok(DemoSummary {
        slo_loaded_before_classify,
        metrics_loaded_before_use,
        slo_loaded_after_classify: provide_telemetry::slo::slo_initialized_for_tests(),
        metrics_loaded_after_use: provide_telemetry::metrics::metrics_initialized_for_tests(),
    })
}
