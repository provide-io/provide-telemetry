// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#[path = "support/performance_metrics.rs"]
mod performance_metrics;

fn main() {
    match performance_metrics::run_demo() {
        Ok(summary) => {
            println!("Rust Performance Demo");
            println!(
                "counter_ns={:.1} event_ns={:.1} should_sample_ns={:.1}",
                summary.counter_ns, summary.event_ns, summary.should_sample_ns
            );
        }
        Err(err) => {
            eprintln!("performance example failed: {err}");
            std::process::exit(1);
        }
    }
}
