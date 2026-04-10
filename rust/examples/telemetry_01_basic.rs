// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#[path = "support/basic_telemetry.rs"]
mod basic_telemetry;

fn main() {
    match basic_telemetry::run_demo() {
        Ok(summary) => {
            println!("Rust Basic Telemetry Demo");
            println!(
                "service={} env={} version={}",
                summary.service_name, summary.environment, summary.version
            );
            println!(
                "iterations={} logs={} counter_total={} gauge_value={} histogram_count={} histogram_total={}",
                summary.iterations,
                summary.logged_events,
                summary.counter_total,
                summary.gauge_value,
                summary.histogram_count,
                summary.histogram_total
            );
            println!(
                "context_keys_after_clear={}",
                summary.context_keys_after_clear
            );
        }
        Err(err) => {
            eprintln!("basic telemetry example failed: {err}");
            std::process::exit(1);
        }
    }
}
