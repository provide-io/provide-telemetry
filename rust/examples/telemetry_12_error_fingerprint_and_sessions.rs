// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#[path = "support/error_sessions.rs"]
mod error_sessions;

fn main() {
    match error_sessions::run_demo() {
        Ok(summary) => {
            println!("Rust Error Fingerprinting and Session Correlation Demo");
            println!(
                "value_error_a={} type_error={} runtime_error={} session_before={:?} session_after_bind={:?} session_after_clear={:?}",
                summary.value_error_a,
                summary.type_error,
                summary.runtime_error_fingerprint,
                summary.session_before,
                summary.session_after_bind,
                summary.session_after_clear
            );
        }
        Err(err) => {
            eprintln!("error/session example failed: {err}");
            std::process::exit(1);
        }
    }
}
