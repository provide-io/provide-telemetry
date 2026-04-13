// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#[cfg(feature = "otel")]
#[path = "support/openobserve_shared.rs"]
mod openobserve_shared;

#[cfg(feature = "otel")]
fn main() {
    let result = (|| -> Result<(), String> {
        let base_url = openobserve_shared::require_env("OPENOBSERVE_URL")?;
        let user = openobserve_shared::require_env("OPENOBSERVE_USER")?;
        let password = openobserve_shared::require_env("OPENOBSERVE_PASSWORD")?;
        let names = openobserve_shared::signal_names(std::env::var("PROVIDE_EXAMPLE_RUN_ID").ok());
        let endpoints = openobserve_shared::OpenObserveEndpoints::new(&base_url);
        let auth = openobserve_shared::auth_header(&user, &password);

        let summary = openobserve_shared::emit_all_signals(
            &endpoints,
            &auth,
            &names,
            "provide-telemetry-rust-examples",
        )?;

        println!("signals emitted run_id={}", summary.run_id);
        Ok(())
    })();

    if let Err(err) = result {
        eprintln!("{err}");
        std::process::exit(1);
    }
}

#[cfg(not(feature = "otel"))]
fn main() {
    eprintln!("openobserve_01_emit_all_signals requires --features otel");
    std::process::exit(1);
}
