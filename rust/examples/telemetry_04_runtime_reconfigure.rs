// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#[path = "support/runtime_reconfigure.rs"]
mod runtime_reconfigure;

fn main() {
    match runtime_reconfigure::run_demo() {
        Ok(summary) => {
            println!("Rust Runtime Reconfigure Demo");
            println!(
                "before={} after_update={} after_reconfigure={} after_reload={}",
                summary.before_logs_rate,
                summary.after_update_logs_rate,
                summary.after_reconfigure_logs_rate,
                summary.after_reload_logs_rate
            );
        }
        Err(err) => {
            eprintln!("runtime reconfigure example failed: {err}");
            std::process::exit(1);
        }
    }
}
