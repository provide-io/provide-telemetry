// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#[path = "support/pii_cardinality.rs"]
mod pii_cardinality;

fn main() {
    match pii_cardinality::run_demo() {
        Ok(summary) => {
            println!("Rust PII & Cardinality Demo");
            println!(
                "hashed_email_len={} credit_card_removed={} truncated_password={:?}",
                summary.hashed_email_len, summary.credit_card_removed, summary.truncated_password
            );
            println!(
                "cardinality_max_values={:?} cardinality_ttl_seconds={:?} pii_rule_count={}",
                summary.cardinality_max_values,
                summary.cardinality_ttl_seconds,
                summary.pii_rule_count
            );
        }
        Err(err) => {
            eprintln!("pii/cardinality example failed: {err}");
            std::process::exit(1);
        }
    }
}
