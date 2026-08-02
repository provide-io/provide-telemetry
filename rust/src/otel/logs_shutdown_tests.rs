// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use super::*;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use opentelemetry::InstrumentationScope;
use opentelemetry_sdk::error::{OTelSdkError, OTelSdkResult};
use opentelemetry_sdk::logs::{LogProcessor, SdkLogRecord, SdkLoggerProvider};

use crate::testing::{acquire_test_state_lock, reset_telemetry_state};

fn test_config() -> TelemetryConfig {
    TelemetryConfig {
        service_name: "test".to_string(),
        ..TelemetryConfig::default()
    }
}

fn reset_logs_test_state() -> std::sync::MutexGuard<'static, ()> {
    let guard = acquire_test_state_lock();
    reset_telemetry_state();
    shutdown_logger_provider(None);
    guard
}

#[derive(Debug)]
struct ShutdownErrorLogProcessor;

#[derive(Debug)]
struct TrackingShutdownLogProcessor {
    force_flush_called: Arc<AtomicBool>,
    shutdown_called: Arc<AtomicBool>,
}

impl LogProcessor for TrackingShutdownLogProcessor {
    fn emit(&self, _record: &mut SdkLogRecord, _instrumentation: &InstrumentationScope) {}

    fn force_flush(&self) -> OTelSdkResult {
        self.force_flush_called.store(true, Ordering::Release);
        Ok(())
    }

    fn shutdown_with_timeout(&self, _timeout: Duration) -> OTelSdkResult {
        self.shutdown_called.store(true, Ordering::Release);
        Ok(())
    }
}

impl LogProcessor for ShutdownErrorLogProcessor {
    fn emit(&self, _record: &mut SdkLogRecord, _instrumentation: &InstrumentationScope) {}

    fn force_flush(&self) -> OTelSdkResult {
        Ok(())
    }

    fn shutdown_with_timeout(&self, _timeout: Duration) -> OTelSdkResult {
        Err(OTelSdkError::InternalFailure("test shutdown".into()))
    }
}

#[test]
fn do_shutdown_logger_provider_reaches_the_sdk_processor() {
    let force_flush_called = Arc::new(AtomicBool::new(false));
    let shutdown_called = Arc::new(AtomicBool::new(false));
    let provider = SdkLoggerProvider::builder()
        .with_log_processor(TrackingShutdownLogProcessor {
            force_flush_called: Arc::clone(&force_flush_called),
            shutdown_called: Arc::clone(&shutdown_called),
        })
        .build();

    do_shutdown_logger_provider(InstalledLoggerProvider {
        provider: Arc::new(provider),
        runtime: ProvideTokioRuntime::test(),
    });

    assert!(force_flush_called.load(Ordering::Acquire));
    assert!(shutdown_called.load(Ordering::Acquire));
}

#[test]
fn shutdown_logger_provider_clears_provider_even_when_processor_shutdown_errors() {
    let _guard = reset_logs_test_state();
    shutdown_logger_provider(None);
    let provider = SdkLoggerProvider::builder()
        .with_resource(super::super::resource::build_resource(&test_config()))
        .with_log_processor(ShutdownErrorLogProcessor)
        .build();
    *crate::_lock::lock(logger_provider_slot()) = Some(InstalledLoggerProvider {
        provider: Arc::new(provider),
        runtime: ProvideTokioRuntime::test(),
    });

    shutdown_logger_provider(None);

    assert!(!logger_provider_installed());
}

#[test]
fn install_skipped_when_otlp_enabled_false_even_with_endpoint() {
    let _guard = reset_logs_test_state();
    let mut cfg = test_config();
    cfg.logging.otlp_endpoint = Some("http://127.0.0.1:1/never".to_string());
    cfg.logging.otlp_enabled = false;
    let resource = super::super::resource::build_resource(&cfg);

    let installed =
        install_logger_provider(&cfg, resource).expect("otlp_enabled=false must not error");
    assert!(!installed);
    assert!(!logger_provider_installed());
}

#[test]
fn shutdown_with_zero_timeout_runs_synchronously() {
    // logs_shutdown_timeout_seconds <= 0 opts out of bounding — the worker
    // thread is never spawned and shutdown runs on the caller's thread.
    let _guard = reset_logs_test_state();
    shutdown_logger_provider(None);

    let mut cfg = test_config();
    cfg.exporter.logs_shutdown_timeout_seconds = 0.0;
    crate::runtime::set_active_config(Some(cfg.clone()));

    let provider = SdkLoggerProvider::builder()
        .with_resource(super::super::resource::build_resource(&cfg))
        .build();
    *crate::_lock::lock(logger_provider_slot()) = Some(InstalledLoggerProvider {
        provider: Arc::new(provider),
        runtime: ProvideTokioRuntime::test(),
    });

    shutdown_logger_provider(None);

    assert!(!logger_provider_installed());
    crate::runtime::set_active_config(None);
}

#[test]
fn shutdown_falls_back_to_default_timeout_when_no_active_config() {
    // get_runtime_config() returns None — shutdown_logger_provider must
    // fall back to the 5.0s default rather than crashing.
    let _guard = reset_logs_test_state();
    shutdown_logger_provider(None);
    crate::runtime::set_active_config(None);

    let provider = SdkLoggerProvider::builder()
        .with_resource(super::super::resource::build_resource(&test_config()))
        .build();
    *crate::_lock::lock(logger_provider_slot()) = Some(InstalledLoggerProvider {
        provider: Arc::new(provider),
        runtime: ProvideTokioRuntime::test(),
    });

    shutdown_logger_provider(None);
    assert!(!logger_provider_installed());
}

/// Log processor whose shutdown outlives the configured deadline. Its own
/// finite ceiling ensures a broken deadline fails instead of hanging tests.
#[derive(Debug)]
struct HangingShutdownProcessor;

impl LogProcessor for HangingShutdownProcessor {
    fn emit(&self, _record: &mut SdkLogRecord, _scope: &InstrumentationScope) {}

    fn force_flush(&self) -> OTelSdkResult {
        Ok(())
    }

    fn shutdown_with_timeout(&self, _timeout: Duration) -> OTelSdkResult {
        std::thread::sleep(Duration::from_secs(1));
        Err(OTelSdkError::InternalFailure("test slow shutdown".into()))
    }
}

#[test]
fn shutdown_abandons_worker_when_deadline_exceeded() {
    let _guard = reset_logs_test_state();
    shutdown_logger_provider(None);

    let mut cfg = test_config();
    // 50ms deadline so the test wall time stays well under a second.
    cfg.exporter.logs_shutdown_timeout_seconds = 0.05;
    crate::runtime::set_active_config(Some(cfg.clone()));

    let provider = SdkLoggerProvider::builder()
        .with_resource(super::super::resource::build_resource(&cfg))
        .with_log_processor(HangingShutdownProcessor)
        .build();
    *crate::_lock::lock(logger_provider_slot()) = Some(InstalledLoggerProvider {
        provider: Arc::new(provider),
        runtime: ProvideTokioRuntime::test(),
    });

    let started = std::time::Instant::now();
    shutdown_logger_provider(None);
    let elapsed = started.elapsed();

    // Slot must be cleared even though the worker thread is still hung.
    assert!(!logger_provider_installed());
    assert!(
        elapsed < Duration::from_millis(500),
        "shutdown took {elapsed:?} despite bounded deadline",
    );
    crate::runtime::set_active_config(None);
}
