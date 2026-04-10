// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#[path = "support/w3c_propagation.rs"]
mod w3c_propagation;

fn main() {
    match w3c_propagation::run_demo() {
        Ok(summary) => {
            println!("Rust W3C Propagation Demo");
            println!("http_trace_id={:?}", summary.http_trace_id);
            println!(
                "manual_trace_id_after_clear={:?}",
                summary.manual_trace_id_after_clear
            );
            println!("nested_outer_restored={:?}", summary.nested_outer_restored);
            println!("nested_after_clear={:?}", summary.nested_after_clear);
        }
        Err(err) => {
            eprintln!("w3c propagation example failed: {err}");
            std::process::exit(1);
        }
    }
}
