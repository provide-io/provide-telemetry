// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use crate::config::TelemetryConfig;
use crate::errors::TelemetryError;

#[cfg(feature = "otel")]
mod endpoint;
#[cfg(feature = "otel")]
pub(crate) mod logs;
#[cfg(feature = "otel")]
pub(crate) mod metrics;
#[cfg(feature = "otel")]
pub(crate) mod resilient;
#[cfg(feature = "otel")]
mod resource;
#[cfg(feature = "otel")]
pub(crate) mod traces;

#[cfg(feature = "otel")]
pub(crate) fn setup_otel(config: &TelemetryConfig) -> Result<(), TelemetryError> {
    // Build the resource once and clone for each provider (cheap — Resource
    // is internally Arc'd).
    let resource = resource::build_resource(config);
    traces::install_tracer_provider(config, resource.clone())?;
    metrics::install_meter_provider(config, resource.clone())?;
    logs::install_logger_provider(config, resource)?;
    Ok(())
}

#[cfg(not(feature = "otel"))]
pub(crate) fn setup_otel(_config: &TelemetryConfig) -> Result<(), TelemetryError> {
    Ok(())
}

pub(crate) fn shutdown_otel() {
    #[cfg(feature = "otel")]
    {
        traces::shutdown_tracer_provider();
        metrics::shutdown_meter_provider();
        logs::shutdown_logger_provider();
    }
}

pub(crate) fn otel_installed() -> bool {
    #[cfg(feature = "otel")]
    {
        traces::tracer_provider_installed()
            || metrics::meter_provider_installed()
            || logs::logger_provider_installed()
    }

    #[cfg(not(feature = "otel"))]
    {
        false
    }
}

pub fn otel_installed_for_tests() -> bool {
    otel_installed()
}

pub fn _reset_otel_for_tests() {
    shutdown_otel();
}
