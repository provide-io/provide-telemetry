// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::sync::atomic::{AtomicBool, Ordering};

use crate::config::TelemetryConfig;
use crate::errors::TelemetryError;

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
pub(crate) fn build_otel_layer(
    config: &TelemetryConfig,
) -> Option<Box<dyn tracing_subscriber::Layer<tracing_subscriber::Registry> + Send + Sync>> {
    use opentelemetry_otlp::{SpanExporter, WithExportConfig, WithHttpConfig};
    use opentelemetry_sdk::trace::SdkTracerProvider;
    use tracing_subscriber::layer::SubscriberExt as _;

    let endpoint = std::env::var("OTEL_EXPORTER_OTLP_ENDPOINT")
        .unwrap_or_else(|_| "http://localhost:4318".to_string());
    let traces_url = format!("{}/v1/traces", endpoint.trim_end_matches('/'));

    let exporter = SpanExporter::builder()
        .with_http()
        .with_endpoint(traces_url)
        .with_headers(config.tracing.otlp_headers.clone())
        .build()
        .ok()?;

    let provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();

    let tracer = opentelemetry::trace::TracerProvider::tracer(&provider, "provide-telemetry");

    // Store provider so shutdown_otel() can flush and close it
    OTEL_PROVIDER.get_or_init(|| std::sync::Mutex::new(Some(provider)));

    Some(
        tracing_opentelemetry::layer()
            .with_tracer(tracer)
            .boxed(),
    )
}

#[cfg(feature = "otel")]
static OTEL_PROVIDER: std::sync::OnceLock<
    std::sync::Mutex<Option<opentelemetry_sdk::trace::SdkTracerProvider>>,
> = std::sync::OnceLock::new();

#[cfg(feature = "otel")]
pub(crate) fn setup_otel(_config: &TelemetryConfig) -> Result<(), TelemetryError> {
    // Provider was already built in build_otel_layer; just mark as installed.
    OTEL_INSTALLED.store(true, Ordering::SeqCst);
    Ok(())
}

#[cfg(not(feature = "otel"))]
pub(crate) fn setup_otel(_config: &TelemetryConfig) -> Result<(), TelemetryError> {
    Ok(())
}

#[cfg(feature = "otel")]
pub(crate) fn shutdown_otel() {
    use opentelemetry::trace::TracerProvider as _;
    if let Some(lock) = OTEL_PROVIDER.get() {
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
