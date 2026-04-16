// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::HashMap;

use super::TelemetryConfig;

pub fn redact_config(cfg: &TelemetryConfig) -> TelemetryConfig {
    fn mask(headers: &HashMap<String, String>) -> HashMap<String, String> {
        headers
            .keys()
            .map(|k| (k.clone(), "***REDACTED***".to_string()))
            .collect()
    }
    let mut out = cfg.clone();
    if !out.logging.otlp_headers.is_empty() {
        out.logging.otlp_headers = mask(&cfg.logging.otlp_headers);
    }
    if !out.tracing.otlp_headers.is_empty() {
        out.tracing.otlp_headers = mask(&cfg.tracing.otlp_headers);
    }
    if !out.metrics.otlp_headers.is_empty() {
        out.metrics.otlp_headers = mask(&cfg.metrics.otlp_headers);
    }
    out
}
