// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// Emit one canonical JSON log line to stderr for cross-language parity checking.
//
// Env vars (set by run_behavioral_parity.py --check-output before invoking):
//   PROVIDE_LOG_FORMAT=json
//   PROVIDE_TELEMETRY_SERVICE_NAME=probe
//   PROVIDE_LOG_INCLUDE_TIMESTAMP=false
//   PROVIDE_LOG_LEVEL=INFO

fn main() {
    provide_telemetry::setup_telemetry().expect("setup_telemetry");
    let _guard = provide_telemetry::set_trace_context(
        Some("0af7651916cd43dd8448eb211c80319c".to_string()),
        Some("b7ad6b7169203331".to_string()),
    );
    let logger = provide_telemetry::get_logger(Some("probe"));
    logger.info("log.output.parity");
}
