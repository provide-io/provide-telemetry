// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#[path = "support/exporter_resilience.rs"]
mod exporter_resilience;

fn main() {
    match exporter_resilience::run_demo() {
        Ok(summary) => {
            println!("Rust Exporter Resilience Demo");
            println!(
                "fail_open_result_is_none={} fail_closed_is_error={} timeout_result_is_none={}",
                summary.fail_open_result_is_none,
                summary.fail_closed_is_error,
                summary.timeout_result_is_none
            );
            println!(
                "metrics_circuit_state={} metrics_open_count={} retries_logs={}",
                summary.metrics_circuit_state, summary.metrics_open_count, summary.retries_logs
            );
        }
        Err(err) => {
            eprintln!("exporter resilience example failed: {err}");
            std::process::exit(1);
        }
    }
}
