// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

//! Drain without teardown — force-flush installed providers, leave them installed.
//!
//! The drain half of the shutdown path. Each provider is cloned out of its slot
//! rather than taken, so telemetry keeps working afterwards, and each flush runs
//! under the bounded-shutdown deadline (see [`super::bounded_flush`]).

use std::sync::Arc;

use super::{logs, metrics, traces};

/// Force-flush the installed provider, leaving it installed and usable.
///
/// The drain half of the shutdown path: the provider is cloned out of its slot
/// rather than taken, so telemetry keeps working afterwards. Returns false when
/// the flush was abandoned at the bounded-shutdown deadline or the exporter
/// rejected it.
pub(crate) fn flush_logger_provider(timeout_seconds: Option<f64>) -> bool {
    let provider = {
        let guard = crate::_lock::lock(logs::logger_provider_slot());
        guard
            .as_ref()
            .map(|installed| Arc::clone(&installed.provider))
    };
    let Some(provider) = provider else {
        return true;
    };

    super::bounded_flush("logs", timeout_seconds, move || {
        provider.force_flush().is_ok()
    })
}

/// Force-flush the installed provider, leaving it installed and usable.
///
/// The drain half of the shutdown path: the provider is cloned out of its slot
/// rather than taken, so telemetry keeps working afterwards. Returns false when
/// the flush was abandoned at the bounded-shutdown deadline or the exporter
/// rejected it.
pub(crate) fn flush_tracer_provider(timeout_seconds: Option<f64>) -> bool {
    let provider = {
        let guard = crate::_lock::lock(traces::tracer_provider_slot());
        guard
            .as_ref()
            .map(|installed| Arc::clone(&installed.provider))
    };
    let Some(provider) = provider else {
        return true;
    };

    super::bounded_flush("traces", timeout_seconds, move || {
        provider.force_flush().is_ok()
    })
}

/// Force-flush the installed provider, leaving it installed and usable.
///
/// The drain half of the shutdown path: the provider is cloned out of its slot
/// rather than taken, so telemetry keeps working afterwards. Returns false when
/// the flush was abandoned at the bounded-shutdown deadline or the exporter
/// rejected it.
pub(crate) fn flush_meter_provider(timeout_seconds: Option<f64>) -> bool {
    let provider = {
        let guard = crate::_lock::lock(metrics::meter_provider_slot());
        guard
            .as_ref()
            .map(|installed| Arc::clone(&installed.provider))
    };
    let Some(provider) = provider else {
        return true;
    };

    super::bounded_flush("metrics", timeout_seconds, move || {
        provider.force_flush().is_ok()
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::TelemetryConfig;
    use crate::testing::{acquire_test_state_lock, reset_telemetry_state};
    use opentelemetry::logs::{Logger as _, LoggerProvider as _};
    use opentelemetry::metrics::MeterProvider as _;
    use opentelemetry::trace::{Span as _, Tracer as _, TracerProvider as _};
    use opentelemetry::{Context, InstrumentationScope};
    use opentelemetry_sdk::error::{OTelSdkError, OTelSdkResult};
    use opentelemetry_sdk::logs::{LogProcessor, SdkLogRecord, SdkLoggerProvider};
    use opentelemetry_sdk::metrics::data::ResourceMetrics;
    use opentelemetry_sdk::metrics::exporter::PushMetricExporter;
    use opentelemetry_sdk::metrics::periodic_reader_with_async_runtime::PeriodicReader;
    use opentelemetry_sdk::metrics::{SdkMeterProvider, Temporality};
    use opentelemetry_sdk::trace::{SdkTracerProvider, Span, SpanData, SpanProcessor};
    use std::sync::atomic::{AtomicBool, Ordering};

    #[derive(Debug)]
    struct BlockingSpanProcessor {
        released: Arc<AtomicBool>,
    }

    #[derive(Debug)]
    struct FlushErrorLogProcessor;

    #[derive(Debug)]
    struct FlushErrorMetricExporter;

    #[test]
    fn failing_flush_test_doubles_expose_their_trait_callbacks() {
        assert!(PushMetricExporter::force_flush(&FlushErrorMetricExporter).is_err());

        let provider = SdkLoggerProvider::builder().build();
        let logger = provider.logger("provide-telemetry.flush-fixture");
        let mut record = logger.create_log_record();
        let scope = InstrumentationScope::builder("provide-telemetry.flush-fixture").build();
        LogProcessor::emit(&FlushErrorLogProcessor, &mut record, &scope);
    }

    impl PushMetricExporter for FlushErrorMetricExporter {
        async fn export(&self, _metrics: &ResourceMetrics) -> OTelSdkResult {
            Err(OTelSdkError::InternalFailure("test export".into()))
        }

        fn force_flush(&self) -> OTelSdkResult {
            Err(OTelSdkError::InternalFailure("test flush".into()))
        }

        fn shutdown_with_timeout(&self, _timeout: std::time::Duration) -> OTelSdkResult {
            Ok(())
        }

        fn temporality(&self) -> Temporality {
            Temporality::Cumulative
        }
    }

    impl LogProcessor for FlushErrorLogProcessor {
        fn emit(&self, _record: &mut SdkLogRecord, _instrumentation: &InstrumentationScope) {}

        fn force_flush(&self) -> OTelSdkResult {
            Err(OTelSdkError::InternalFailure("test flush".into()))
        }

        fn shutdown_with_timeout(&self, _timeout: std::time::Duration) -> OTelSdkResult {
            Ok(())
        }
    }

    impl SpanProcessor for BlockingSpanProcessor {
        fn on_start(&self, _span: &mut Span, _cx: &Context) {}

        fn on_end(&self, _span: SpanData) {}

        fn force_flush(&self) -> OTelSdkResult {
            // Keep an independent ceiling so a broken library deadline fails
            // this test instead of hanging the entire mutation suite.
            let started = std::time::Instant::now();
            while !self.released.load(Ordering::Acquire)
                && started.elapsed() < std::time::Duration::from_millis(250)
            {
                std::thread::sleep(std::time::Duration::from_millis(5));
            }
            Ok(())
        }

        fn shutdown_with_timeout(&self, _timeout: std::time::Duration) -> OTelSdkResult {
            Ok(())
        }
    }

    fn install_config() -> TelemetryConfig {
        // A syntactically valid endpoint that nothing listens on: the provider
        // installs, so the flush path runs against a real SDK provider, and the
        // export itself is irrelevant to what these tests pin.
        let mut cfg = TelemetryConfig {
            service_name: "flush-test".to_string(),
            ..TelemetryConfig::default()
        };
        cfg.tracing.enabled = true;
        cfg.tracing.otlp_endpoint = Some("http://127.0.0.1:4318/v1/traces".to_string());
        cfg.metrics.enabled = true;
        cfg.metrics.otlp_endpoint = Some("http://127.0.0.1:4318/v1/metrics".to_string());
        cfg.logging.otlp_endpoint = Some("http://127.0.0.1:4318/v1/logs".to_string());
        cfg
    }

    // Nothing installed is a drained state: the caller asked for the queue to be
    // empty and it is. Reporting failure here would make flush unusable in
    // cleanup paths that run before setup or after shutdown.
    #[test]
    fn flushing_with_no_provider_installed_succeeds() {
        let _guard = acquire_test_state_lock();
        reset_telemetry_state();

        assert!(flush_logger_provider(None));
        assert!(flush_tracer_provider(None));
        assert!(flush_meter_provider(None));
    }

    #[test]
    fn logger_flush_surfaces_processor_failure() {
        let _guard = acquire_test_state_lock();
        reset_telemetry_state();

        let provider = SdkLoggerProvider::builder()
            .with_log_processor(FlushErrorLogProcessor)
            .build();
        logs::install_logger_provider_for_tests(provider);

        assert!(!flush_logger_provider(None));
        reset_telemetry_state();
    }

    #[test]
    fn meter_flush_surfaces_exporter_failure() {
        let _guard = acquire_test_state_lock();
        reset_telemetry_state();

        let reader = PeriodicReader::builder(
            FlushErrorMetricExporter,
            super::super::async_runtime::ProvideTokioRuntime::test(),
        )
        .with_interval(std::time::Duration::from_secs(60))
        .build();
        let provider = SdkMeterProvider::builder().with_reader(reader).build();
        provider
            .meter("provide-telemetry.flush-test")
            .u64_counter("flush.test.counter")
            .build()
            .add(1, &[]);
        metrics::install_meter_provider_for_tests(provider);

        assert!(!flush_meter_provider(None));
        reset_telemetry_state();
    }

    /// crate::flush_telemetry(None) must surface an incomplete drain as Err — the
    /// whole point of flush over shutdown is that the caller learns when its
    /// records did not make it out. A deliberately blocked processor makes the
    /// outcome independent of scheduler speed and exporter implementation.
    #[test]
    fn flush_telemetry_reports_an_incomplete_drain_as_an_error() {
        let _guard = acquire_test_state_lock();
        reset_telemetry_state();

        let released = Arc::new(AtomicBool::new(false));
        let provider = SdkTracerProvider::builder()
            .with_span_processor(BlockingSpanProcessor {
                released: Arc::clone(&released),
            })
            .build();
        let mut span = provider
            .tracer("provide-telemetry.flush-test")
            .start("blocked.flush");
        span.end();
        super::super::traces::install_tracer_provider_for_tests(provider);

        let mut cfg = TelemetryConfig::default();
        cfg.exporter.logs_shutdown_timeout_seconds = 0.05;
        crate::runtime::set_active_config(Some(cfg));

        assert!(
            crate::flush_telemetry(None).is_err(),
            "a drain abandoned at its deadline must report Err"
        );

        released.store(true, Ordering::Release);
        crate::runtime::set_active_config(None);
        reset_telemetry_state();
    }

    // The installed path: each provider is cloned out of its slot rather than
    // taken, so the flush runs and the provider is still installed afterwards.
    // Without this the whole cloned-not-taken branch is unexercised.
    #[test]
    fn flushing_an_installed_provider_leaves_it_installed() {
        let _guard = acquire_test_state_lock();
        reset_telemetry_state();

        let cfg = install_config();
        let resource = super::super::resource::build_resource(&cfg);
        let _ = super::super::traces::install_tracer_provider(&cfg, resource.clone());
        let _ = super::super::metrics::install_meter_provider(&cfg, resource.clone());
        let _ = super::super::logs::install_logger_provider(&cfg, resource);

        // Each returns true: the drain completed inside the bounded deadline.
        assert!(flush_tracer_provider(None));
        assert!(flush_meter_provider(None));
        assert!(flush_logger_provider(None));

        // Still installed — that is the whole point of flush over shutdown.
        assert!(super::super::traces::tracer_provider_installed());
        assert!(super::super::metrics::meter_provider_installed());
        assert!(super::super::logs::logger_provider_installed());

        // And repeatable.
        assert!(flush_tracer_provider(None));
        assert!(flush_meter_provider(None));
        assert!(flush_logger_provider(None));

        reset_telemetry_state();
    }
}
