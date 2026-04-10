// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use provide_telemetry::{
    get_runtime_config, reconfigure_telemetry, reload_runtime_from_env, setup_telemetry,
    shutdown_telemetry, update_runtime_config, RuntimeOverrides, SamplingConfig, TelemetryError,
};

#[derive(Debug, Clone, PartialEq)]
pub struct DemoSummary {
    pub before_logs_rate: f64,
    pub after_update_logs_rate: f64,
    pub after_reconfigure_logs_rate: f64,
    pub after_reload_logs_rate: f64,
}

fn restore_var(key: &str, previous: Option<String>) {
    match previous {
        Some(value) => std::env::set_var(key, value),
        None => std::env::remove_var(key),
    }
}

pub fn run_demo() -> Result<DemoSummary, TelemetryError> {
    let _ = shutdown_telemetry();
    setup_telemetry()?;

    let before_logs_rate = get_runtime_config()
        .map(|cfg| cfg.sampling.logs_rate)
        .unwrap_or(1.0);

    let after_update_logs_rate = update_runtime_config(RuntimeOverrides {
        sampling: Some(SamplingConfig {
            logs_rate: 0.0,
            traces_rate: 1.0,
            metrics_rate: 1.0,
        }),
        ..RuntimeOverrides::default()
    })?
    .sampling
    .logs_rate;

    let mut reconfigured = get_runtime_config().unwrap_or_default();
    reconfigured.sampling = SamplingConfig {
        logs_rate: 1.0,
        traces_rate: 1.0,
        metrics_rate: 1.0,
    };
    let after_reconfigure_logs_rate = reconfigure_telemetry(Some(reconfigured))?
        .sampling
        .logs_rate;

    let env_key = "PROVIDE_SAMPLING_LOGS_RATE";
    let previous = std::env::var(env_key).ok();
    std::env::set_var(env_key, "1.0");
    let after_reload_logs_rate = reload_runtime_from_env()?.sampling.logs_rate;
    restore_var(env_key, previous);

    shutdown_telemetry()?;
    Ok(DemoSummary {
        before_logs_rate,
        after_update_logs_rate,
        after_reconfigure_logs_rate,
        after_reload_logs_rate,
    })
}
