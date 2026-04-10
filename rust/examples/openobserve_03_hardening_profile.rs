// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#[cfg(feature = "otel")]
use provide_telemetry::{
    get_health_snapshot, register_cardinality_limit, register_pii_rule, set_exporter_policy,
    set_queue_policy, set_sampling_policy, CardinalityLimit, ExporterPolicy, PIIMode, PIIRule,
    QueuePolicy, SamplingPolicy, Signal,
};

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

        register_pii_rule(PIIRule::new(
            vec!["user".into(), "email".into()],
            PIIMode::Hash,
            0,
        ));
        register_pii_rule(PIIRule::new(
            vec!["user".into(), "full_name".into()],
            PIIMode::Truncate,
            4,
        ));
        register_cardinality_limit(
            "player_id",
            CardinalityLimit {
                max_values: 50,
                ttl_seconds: 300.0,
            },
        );
        let _ = set_sampling_policy(
            Signal::Logs,
            SamplingPolicy {
                default_rate: 1.0,
                overrides: Default::default(),
            },
        );
        let _ = set_sampling_policy(
            Signal::Traces,
            SamplingPolicy {
                default_rate: 1.0,
                overrides: Default::default(),
            },
        );
        let _ = set_sampling_policy(
            Signal::Metrics,
            SamplingPolicy {
                default_rate: 1.0,
                overrides: Default::default(),
            },
        );
        set_queue_policy(QueuePolicy {
            logs_maxsize: 0,
            traces_maxsize: 64,
            metrics_maxsize: 0,
        });
        let _ = set_exporter_policy(
            Signal::Logs,
            ExporterPolicy {
                retries: 1,
                backoff_seconds: 0.0,
                timeout_seconds: 5.0,
                fail_open: true,
                allow_blocking_in_event_loop: false,
            },
        );
        let _ = set_exporter_policy(
            Signal::Traces,
            ExporterPolicy {
                retries: 1,
                backoff_seconds: 0.0,
                timeout_seconds: 5.0,
                fail_open: true,
                allow_blocking_in_event_loop: false,
            },
        );
        let _ = set_exporter_policy(
            Signal::Metrics,
            ExporterPolicy {
                retries: 1,
                backoff_seconds: 0.0,
                timeout_seconds: 5.0,
                fail_open: true,
                allow_blocking_in_event_loop: false,
            },
        );

        let summary = openobserve_shared::emit_all_signals(
            &endpoints,
            &auth,
            &names,
            "provide-telemetry-rust-hardening-example",
        )?;
        println!(
            "{{\"run_id\":\"{}\",\"health\":{:?}}}",
            summary.run_id,
            get_health_snapshot()
        );
        Ok(())
    })();

    if let Err(err) = result {
        eprintln!("{err}");
        std::process::exit(1);
    }
}

#[cfg(not(feature = "otel"))]
fn main() {
    eprintln!("openobserve_03_hardening_profile requires --features otel");
    std::process::exit(1);
}
