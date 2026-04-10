// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#[path = "support/lazy_loading.rs"]
mod lazy_loading;

fn main() {
    match lazy_loading::run_demo() {
        Ok(summary) => {
            println!("Rust Lazy Loading Proof");
            println!(
                "slo_before={} metrics_before={} slo_after={} metrics_after={}",
                summary.slo_loaded_before_classify,
                summary.metrics_loaded_before_use,
                summary.slo_loaded_after_classify,
                summary.metrics_loaded_after_use
            );
        }
        Err(err) => {
            eprintln!("lazy loading example failed: {err}");
            std::process::exit(1);
        }
    }
}
