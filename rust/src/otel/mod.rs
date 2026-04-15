// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::sync::atomic::{AtomicBool, Ordering};

use crate::config::TelemetryConfig;
use crate::errors::TelemetryError;

#[cfg(feature = "otel")]
mod endpoint;
#[cfg(feature = "otel")]
mod resource;
#[cfg(feature = "otel")]
pub(crate) mod traces;

static OTEL_INSTALLED: AtomicBool = AtomicBool::new(false);

// Non-otel: subscriber layer is always None
#[cfg(not(feature = "otel"))]
pub(crate) fn build_otel_layer(
    _config: &TelemetryConfig,
) -> Option<Box<dyn tracing_subscriber::Layer<tracing_subscriber::Registry> + Send + Sync>> {
    None
}

// Otel: build OTLP-backed TracerProvider and return a tracing-opentelemetry layer
#[cfg(feature = "otel")]
pub(crate) fn setup_otel(config: &TelemetryConfig) -> Result<(), TelemetryError> {
    let resource = resource::build_resource(config);
    traces::install_tracer_provider(config, resource)?;
    OTEL_INSTALLED.store(true, Ordering::SeqCst);
    Ok(())
}

#[cfg(not(feature = "otel"))]
pub(crate) fn setup_otel(_config: &TelemetryConfig) -> Result<(), TelemetryError> {
    Ok(())
}

#[cfg(feature = "otel")]
pub(crate) fn shutdown_otel() {
    // Flush and shut down trace provider
    if let Some(lock) = OTEL_PROVIDER.get() {
        if let Ok(mut guard) = lock.lock() {
            if let Some(provider) = guard.take() {
                let _ = provider.shutdown();
            }
        }
    }
    // Flush and shut down log provider
    if let Some(lock) = OTEL_LOG_PROVIDER.get() {
        if let Ok(mut guard) = lock.lock() {
            if let Some(provider) = guard.take() {
                let _ = provider.shutdown();
            }
        }
    }
    // Flush and shut down meter provider
    if let Some(lock) = OTEL_METER_PROVIDER.get() {
        if let Ok(mut guard) = lock.lock() {
            if let Some(provider) = guard.take() {
                let _ = provider.shutdown();
            }
        }
    }
    OTEL_INSTALLED.store(false, Ordering::SeqCst);
}

#[cfg(not(feature = "otel"))]
pub(crate) fn shutdown_otel() {
    #[cfg(feature = "otel")]
    traces::shutdown_tracer_provider();
    OTEL_INSTALLED.store(false, Ordering::SeqCst);
}

pub fn otel_installed() -> bool {
    OTEL_INSTALLED.load(Ordering::SeqCst)
}

pub fn otel_installed_for_tests() -> bool {
    otel_installed()
}

pub fn _reset_otel_for_tests() {
    shutdown_otel();
}
