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

static OTEL_INSTALLED: AtomicBool = AtomicBool::new(false);

#[cfg(feature = "otel")]
pub(crate) fn setup_otel(_config: &TelemetryConfig) -> Result<(), TelemetryError> {
    OTEL_INSTALLED.store(true, Ordering::SeqCst);
    Ok(())
}

#[cfg(not(feature = "otel"))]
pub(crate) fn setup_otel(_config: &TelemetryConfig) -> Result<(), TelemetryError> {
    Ok(())
}

pub(crate) fn shutdown_otel() {
    OTEL_INSTALLED.store(false, Ordering::SeqCst);
}

pub(crate) fn otel_installed() -> bool {
    OTEL_INSTALLED.load(Ordering::SeqCst)
}

pub fn otel_installed_for_tests() -> bool {
    otel_installed()
}

pub fn _reset_otel_for_tests() {
    shutdown_otel();
}
