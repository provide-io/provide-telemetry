// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Emit observed config metadata for the Rust SDK.
//!
//! `spec/check_config_parity.py` shells out to this example and diffs the JSON
//! line below against `spec/telemetry-api.yaml`. The measurement itself lives in
//! the library (`provide_telemetry::testing::config_defaults_probe`), so this
//! process and the in-repo `config_applicability` test observe the same thing —
//! a probe that only existed here could drift from the crate it claims to
//! describe without any test noticing.

use std::env;

use provide_telemetry::testing::config_defaults_probe;

fn main() {
    let env_vars: Vec<String> = env::args().skip(1).collect();
    if env_vars.is_empty() {
        eprintln!("usage: config_probe ENV_VAR [ENV_VAR ...]");
        std::process::exit(2);
    }

    let entries = config_defaults_probe(&env_vars);
    let payload = serde_json::json!({ "language": "rust", "entries": entries });
    println!("{payload}");
}
