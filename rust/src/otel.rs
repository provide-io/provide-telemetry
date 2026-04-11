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
    use tracing_subscriber::Layer as _;

    let endpoint = std::env::var("OTEL_EXPORTER_OTLP_ENDPOINT")
        .unwrap_or_else(|_| "http://localhost:4318".to_string());
    let traces_url = format!("{}/v1/traces", endpoint.trim_end_matches('/'));

    // Use a blocking reqwest client so span export works without requiring a
    // running Tokio reactor at call time.
    let http_client = reqwest::blocking::Client::builder().build().ok()?;

    let exporter = SpanExporter::builder()
        .with_http()
        .with_http_client(http_client)
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

// Otel: build OTLP-backed LoggerProvider and return an appender-tracing bridge layer
#[cfg(feature = "otel")]
pub(crate) fn build_otel_log_layer(
    config: &TelemetryConfig,
) -> Option<Box<dyn tracing_subscriber::Layer<tracing_subscriber::Registry> + Send + Sync>> {
    use opentelemetry_otlp::{LogExporter, WithExportConfig, WithHttpConfig};
    use opentelemetry_sdk::logs::SdkLoggerProvider;
    use tracing_subscriber::Layer as _;

    let endpoint = std::env::var("OTEL_EXPORTER_OTLP_ENDPOINT")
        .unwrap_or_else(|_| "http://localhost:4318".to_string());
    let logs_url = format!("{}/v1/logs", endpoint.trim_end_matches('/'));

    // Use a blocking reqwest client so log export works without requiring a
    // running Tokio reactor at call time.
    let http_client = reqwest::blocking::Client::builder().build().ok()?;

    let exporter = LogExporter::builder()
        .with_http()
        .with_http_client(http_client)
        .with_endpoint(logs_url)
        .with_headers(config.logging.otlp_headers.clone())
        .build()
        .ok()?;

    let provider = SdkLoggerProvider::builder()
        .with_simple_exporter(exporter)
        .build();

    // Store provider so shutdown_otel() can flush and close it
    OTEL_LOG_PROVIDER.get_or_init(|| std::sync::Mutex::new(Some(provider.clone())));

    Some(
        opentelemetry_appender_tracing::layer::OpenTelemetryTracingBridge::new(&provider).boxed(),
    )
}

// Non-otel: log layer is always None
#[cfg(not(feature = "otel"))]
pub(crate) fn build_otel_log_layer(
    _config: &TelemetryConfig,
) -> Option<Box<dyn tracing_subscriber::Layer<tracing_subscriber::Registry> + Send + Sync>> {
    None
}

#[cfg(feature = "otel")]
static OTEL_PROVIDER: std::sync::OnceLock<
    std::sync::Mutex<Option<opentelemetry_sdk::trace::SdkTracerProvider>>,
> = std::sync::OnceLock::new();

#[cfg(feature = "otel")]
static OTEL_LOG_PROVIDER: std::sync::OnceLock<
    std::sync::Mutex<Option<opentelemetry_sdk::logs::SdkLoggerProvider>>,
> = std::sync::OnceLock::new();

#[cfg(feature = "otel")]
static OTEL_METER_PROVIDER: std::sync::OnceLock<
    std::sync::Mutex<Option<opentelemetry_sdk::metrics::SdkMeterProvider>>,
> = std::sync::OnceLock::new();

#[cfg(feature = "otel")]
pub(crate) fn setup_otel_meter(config: &TelemetryConfig) -> Result<(), TelemetryError> {
    use opentelemetry_otlp::{MetricExporter, WithExportConfig, WithHttpConfig};
    use opentelemetry_sdk::metrics::{PeriodicReader, SdkMeterProvider};

    let endpoint = std::env::var("OTEL_EXPORTER_OTLP_ENDPOINT")
        .unwrap_or_else(|_| "http://localhost:4318".to_string());
    let metrics_url = format!("{}/v1/metrics", endpoint.trim_end_matches('/'));

    // Use a blocking reqwest client so the export thread can make HTTP requests
    // without needing an external Tokio runtime at provider-creation time.
    // The PeriodicReader spawns its own dedicated thread (not inside tokio),
    // so blocking I/O is safe here.
    let http_client = reqwest::blocking::Client::builder()
        .build()
        .map_err(|err| TelemetryError::new(format!("failed to build HTTP client: {err}")))?;

    let exporter = MetricExporter::builder()
        .with_http()
        .with_http_client(http_client)
        .with_endpoint(metrics_url)
        .with_headers(config.metrics.otlp_headers.clone())
        .build()
        .map_err(|err| TelemetryError::new(format!("failed to build metric exporter: {err}")))?;

    let reader = PeriodicReader::builder(exporter).build();
    let provider = SdkMeterProvider::builder()
        .with_reader(reader)
        .build();

    // Set as the global meter provider so opentelemetry::global::meter() works
    opentelemetry::global::set_meter_provider(provider.clone());

    // Store provider so shutdown_otel() can flush and close it
    OTEL_METER_PROVIDER.get_or_init(|| std::sync::Mutex::new(Some(provider)));

    Ok(())
}

#[cfg(feature = "otel")]
pub(crate) fn setup_otel(config: &TelemetryConfig) -> Result<(), TelemetryError> {
    // Provider was already built in build_otel_layer; set up meter provider here.
    setup_otel_meter(config)?;
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
