// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#[path = "support/data_governance.rs"]
mod data_governance;

fn main() {
    match data_governance::run_demo() {
        Ok(summary) => {
            println!("Rust Data Governance Demo");
            println!(
                "logs_debug={} traces_none={} ssn={:?} card_len={:?} receipt_action={:?}",
                summary.full_logs_debug_allowed,
                summary.none_traces_allowed,
                summary.redacted_ssn,
                summary.hashed_card_len,
                summary.receipt_action
            );
        }
        Err(err) => {
            eprintln!("data governance example failed: {err}");
            std::process::exit(1);
        }
    }
}
