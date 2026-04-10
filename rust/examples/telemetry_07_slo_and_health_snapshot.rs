// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#[path = "support/slo_health.rs"]
mod slo_health;

fn main() {
    match slo_health::run_demo() {
        Ok(summary) => {
            println!("Rust SLO & Health Demo");
            println!(
                "classify_404={:?} classify_503={:?} classify_200={:?} dropped_logs={}",
                summary.classify_404,
                summary.classify_503,
                summary.classify_200,
                summary.dropped_logs
            );
        }
        Err(err) => {
            eprintln!("slo example failed: {err}");
            std::process::exit(1);
        }
    }
}
