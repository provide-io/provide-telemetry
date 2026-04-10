// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#[path = "support/sampling_backpressure.rs"]
mod sampling_backpressure;

fn main() {
    match sampling_backpressure::run_demo() {
        Ok(summary) => {
            println!("Rust Sampling & Backpressure Demo");
            println!(
                "logs_routine_sampled={} logs_critical_sampled={}",
                summary.logs_routine_sampled, summary.logs_critical_sampled
            );
            println!(
                "tickets first={} second={} third={}",
                summary.first_trace_ticket_acquired,
                summary.second_trace_ticket_acquired,
                summary.third_trace_ticket_acquired
            );
            println!(
                "dropped_traces={} logs_policy_rate={} traces_queue_size={}",
                summary.dropped_traces, summary.logs_policy_rate, summary.traces_queue_size
            );
        }
        Err(err) => {
            eprintln!("sampling/backpressure example failed: {err}");
            std::process::exit(1);
        }
    }
}
