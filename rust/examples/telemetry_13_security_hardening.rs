// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#[path = "support/security_hardening.rs"]
mod security_hardening;

fn main() {
    match security_hardening::run_demo() {
        Ok(summary) => {
            println!("Rust Security Hardening Demo");
            println!(
                "secret_redacted={} password_redacted={} depth_preserved_leaf={:?}",
                summary.secret_redacted, summary.password_redacted, summary.depth_preserved_leaf
            );
        }
        Err(err) => {
            eprintln!("security hardening example failed: {err}");
            std::process::exit(1);
        }
    }
}
