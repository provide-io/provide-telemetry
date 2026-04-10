// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#[path = "support/error_degradation.rs"]
mod error_degradation;

fn main() {
    match error_degradation::run_demo() {
        Ok(summary) => {
            println!("Rust Error Handling & Degradation Demo");
            println!(
                "configuration_error_seen={} event_schema_error_seen={} telemetry_error_catchall_count={}",
                summary.configuration_error_seen,
                summary.event_schema_error_seen,
                summary.telemetry_error_catchall_count
            );
        }
        Err(err) => {
            eprintln!("error handling example failed: {err}");
            std::process::exit(1);
        }
    }
}
