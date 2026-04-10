// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#[path = "support/full_hardening.rs"]
mod full_hardening;

fn main() {
    match full_hardening::run_demo() {
        Ok(summary) => {
            println!("Rust Full Hardening Demo");
            println!(
                "pii_rules_active={} cardinality_limit_max={:?} queue_traces_maxsize={} metrics_circuit_state={}",
                summary.pii_rules_active,
                summary.cardinality_limit_max,
                summary.queue_traces_maxsize,
                summary.metrics_circuit_state
            );
        }
        Err(err) => {
            eprintln!("full hardening example failed: {err}");
            std::process::exit(1);
        }
    }
}
