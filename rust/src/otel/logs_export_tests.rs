use super::*;

use std::time::Duration;

use super::export_test_support::{
    assert_export_health_success, export_health_success, export_test_config, reset_all_otel_state,
    settle_otel_exports, wait_for_export_health, MockOtlpCollector,
};
use crate::testing::acquire_test_state_lock;
use crate::{get_logger, trace};

#[test]
fn logger_provider_shutdown_exports_logs_to_http_endpoint() {
    let _guard = acquire_test_state_lock();

    for attempt in 0..5 {
        reset_all_otel_state();

        let collector = MockOtlpCollector::start();
        let cfg = export_test_config(&collector.endpoint);
        let resource = super::super::resource::build_resource(&cfg);
        let installed =
            install_logger_provider(&cfg, resource).expect("install should succeed for mock HTTP");
        assert!(
            installed,
            "attempt {attempt}: logger provider should install"
        );
        assert!(
            logger_provider_installed(),
            "attempt {attempt}: logger provider should be installed"
        );

        emit_log(&LogEvent {
            level: "INFO".to_string(),
            target: "tests.otel.logs".to_string(),
            message: "collector smoke".to_string(),
            context: Default::default(),
            trace_id: None,
            span_id: None,
            event_metadata: None,
        });

        settle_otel_exports();
        shutdown_logger_provider();
        let health = wait_for_export_health(true, false, false, Duration::from_secs(5));
        if export_health_success(&health, true, false, false) {
            break;
        }
        if attempt == 4 {
            assert_export_health_success(&health, true, false, false);
        }
    }

    reset_all_otel_state();
}

#[test]
fn logger_provider_shutdown_exports_logs_with_trace_context_to_http_endpoint() {
    let _guard = acquire_test_state_lock();

    for attempt in 0..5 {
        reset_all_otel_state();

        let collector = MockOtlpCollector::start();
        let cfg = export_test_config(&collector.endpoint);
        let resource = super::super::resource::build_resource(&cfg);
        let installed =
            install_logger_provider(&cfg, resource).expect("install should succeed for mock HTTP");
        assert!(
            installed,
            "attempt {attempt}: logger provider should install"
        );

        emit_log(&LogEvent {
            level: "INFO".to_string(),
            target: "tests.otel.logs".to_string(),
            message: "collector smoke with trace context".to_string(),
            context: Default::default(),
            trace_id: Some("0123456789abcdef0123456789abcdef".to_string()),
            span_id: Some("0123456789abcdef".to_string()),
            event_metadata: None,
        });

        settle_otel_exports();
        shutdown_logger_provider();
        let health = wait_for_export_health(true, false, false, Duration::from_secs(5));
        if export_health_success(&health, true, false, false) {
            break;
        }
        if attempt == 4 {
            assert_export_health_success(&health, true, false, false);
        }
    }

    reset_all_otel_state();
}

#[test]
fn tracer_and_logger_providers_export_both_signals_to_http_endpoints() {
    let _guard = acquire_test_state_lock();

    for attempt in 0..5 {
        reset_all_otel_state();

        let collector = MockOtlpCollector::start();
        let mut cfg = export_test_config(&collector.endpoint);
        cfg.metrics.enabled = false;
        cfg.tracing.otlp_endpoint = Some(format!("{}/v1/traces", collector.endpoint));
        let resource = super::super::resource::build_resource(&cfg);
        let traces_installed =
            super::super::traces::install_tracer_provider(&cfg, resource.clone())
                .expect("tracer provider should install");
        let logs_installed =
            install_logger_provider(&cfg, resource).expect("logger provider should install");
        assert!(
            traces_installed,
            "attempt {attempt}: tracer provider should install"
        );
        assert!(
            logs_installed,
            "attempt {attempt}: logger provider should install"
        );

        let logger = get_logger(Some("tests.otel.combo"));
        trace("tests.otel.span", || {
            logger.info("collector smoke via trace");
        });

        settle_otel_exports();
        super::super::traces::shutdown_tracer_provider();
        shutdown_logger_provider();
        let health = wait_for_export_health(true, true, false, Duration::from_secs(5));
        if export_health_success(&health, true, true, false) {
            break;
        }
        if attempt == 4 {
            assert_export_health_success(&health, true, true, false);
        }
    }

    reset_all_otel_state();
}

#[test]
fn tracer_logger_and_meter_providers_do_not_block_trace_and_log_exports() {
    let _guard = acquire_test_state_lock();

    for attempt in 0..5 {
        reset_all_otel_state();

        let collector = MockOtlpCollector::start();
        let mut cfg = export_test_config(&collector.endpoint);
        cfg.metrics.otlp_endpoint = Some(format!("{}/v1/metrics", collector.endpoint));
        cfg.tracing.otlp_endpoint = Some(format!("{}/v1/traces", collector.endpoint));
        let resource = super::super::resource::build_resource(&cfg);
        let traces_installed =
            super::super::traces::install_tracer_provider(&cfg, resource.clone())
                .expect("tracer provider should install");
        let metrics_installed =
            super::super::metrics::install_meter_provider(&cfg, resource.clone())
                .expect("meter provider should install");
        let logs_installed =
            install_logger_provider(&cfg, resource).expect("logger provider should install");
        assert!(
            traces_installed,
            "attempt {attempt}: tracer provider should install"
        );
        assert!(
            metrics_installed,
            "attempt {attempt}: meter provider should install"
        );
        assert!(
            logs_installed,
            "attempt {attempt}: logger provider should install"
        );

        let logger = get_logger(Some("tests.otel.combo"));
        trace("tests.otel.span", || {
            logger.info("collector smoke via trace with metrics installed");
        });

        settle_otel_exports();
        super::super::traces::shutdown_tracer_provider();
        shutdown_logger_provider();
        super::super::metrics::shutdown_meter_provider();
        let health = wait_for_export_health(true, true, false, Duration::from_secs(5));
        if export_health_success(&health, true, true, false) {
            break;
        }
        if attempt == 4 {
            assert_export_health_success(&health, true, true, false);
        }
    }

    reset_all_otel_state();
}

#[test]
fn runtime_state_does_not_block_trace_and_log_exports_with_all_providers_installed() {
    let _guard = acquire_test_state_lock();

    for attempt in 0..5 {
        reset_all_otel_state();

        let collector = MockOtlpCollector::start();
        let mut cfg = export_test_config(&collector.endpoint);
        cfg.metrics.otlp_endpoint = Some(format!("{}/v1/metrics", collector.endpoint));
        cfg.tracing.otlp_endpoint = Some(format!("{}/v1/traces", collector.endpoint));
        let resource = super::super::resource::build_resource(&cfg);
        let traces_installed =
            super::super::traces::install_tracer_provider(&cfg, resource.clone())
                .expect("tracer provider should install");
        let metrics_installed =
            super::super::metrics::install_meter_provider(&cfg, resource.clone())
                .expect("meter provider should install");
        let logs_installed =
            install_logger_provider(&cfg, resource).expect("logger provider should install");
        assert!(
            traces_installed,
            "attempt {attempt}: tracer provider should install"
        );
        assert!(
            metrics_installed,
            "attempt {attempt}: meter provider should install"
        );
        assert!(
            logs_installed,
            "attempt {attempt}: logger provider should install"
        );

        crate::runtime::set_active_config(Some(cfg.clone()));
        crate::policies::apply_policies(&cfg);

        let logger = get_logger(Some("tests.otel.combo"));
        trace("tests.otel.span", || {
            logger.info("collector smoke via trace with runtime state");
        });

        settle_otel_exports();
        shutdown_logger_provider();
        super::super::metrics::shutdown_meter_provider();
        super::super::traces::shutdown_tracer_provider();
        crate::runtime::set_active_config(None);
        let health = wait_for_export_health(true, true, false, Duration::from_secs(5));
        if export_health_success(&health, true, true, false) {
            break;
        }
        if attempt == 4 {
            assert_export_health_success(&health, true, true, false);
        }
    }

    reset_all_otel_state();
}

#[test]
fn active_config_alone_does_not_block_trace_and_log_exports() {
    let _guard = acquire_test_state_lock();

    reset_all_otel_state();

    let collector = MockOtlpCollector::start();
    let mut cfg = export_test_config(&collector.endpoint);
    cfg.metrics.otlp_endpoint = Some(format!("{}/v1/metrics", collector.endpoint));
    cfg.tracing.otlp_endpoint = Some(format!("{}/v1/traces", collector.endpoint));
    let resource = super::super::resource::build_resource(&cfg);
    assert!(
        super::super::traces::install_tracer_provider(&cfg, resource.clone())
            .expect("tracer provider should install")
    );
    assert!(
        super::super::metrics::install_meter_provider(&cfg, resource.clone())
            .expect("meter provider should install")
    );
    assert!(install_logger_provider(&cfg, resource).expect("logger provider should install"));

    crate::runtime::set_active_config(Some(cfg));
    let logger = get_logger(Some("tests.otel.combo"));
    trace("tests.otel.span", || {
        logger.info("collector smoke via trace with active config");
    });

    settle_otel_exports();
    shutdown_logger_provider();
    super::super::metrics::shutdown_meter_provider();
    super::super::traces::shutdown_tracer_provider();
    crate::runtime::set_active_config(None);
    let health = wait_for_export_health(true, true, false, Duration::from_secs(5));
    assert_export_health_success(&health, true, true, false);

    reset_all_otel_state();
}

#[test]
fn apply_policies_alone_does_not_block_direct_log_exports() {
    let _guard = acquire_test_state_lock();

    reset_all_otel_state();

    let collector = MockOtlpCollector::start();
    let cfg = export_test_config(&collector.endpoint);
    let resource = super::super::resource::build_resource(&cfg);
    assert!(install_logger_provider(&cfg, resource).expect("logger provider should install"));

    crate::policies::apply_policies(&cfg);
    emit_log(&LogEvent {
        level: "INFO".to_string(),
        target: "tests.otel.logs".to_string(),
        message: "collector smoke via direct log with runtime policies".to_string(),
        context: Default::default(),
        trace_id: None,
        span_id: None,
        event_metadata: None,
    });

    settle_otel_exports();
    shutdown_logger_provider();
    let health = crate::health::get_health_snapshot();
    let seen = collector.wait_for_path("/v1/logs", Duration::from_secs(5));
    assert!(
        seen.iter().any(|path| path == "/v1/logs"),
        "expected /v1/logs export, saw {seen:?}; health={health:?}"
    );

    reset_all_otel_state();
}

#[test]
fn apply_policies_alone_does_not_block_direct_trace_exports() {
    let _guard = acquire_test_state_lock();

    reset_all_otel_state();

    let collector = MockOtlpCollector::start();
    let mut cfg = export_test_config(&collector.endpoint);
    cfg.tracing.otlp_endpoint = Some(format!("{}/v1/traces", collector.endpoint));
    let resource = super::super::resource::build_resource(&cfg);
    assert!(
        super::super::traces::install_tracer_provider(&cfg, resource)
            .expect("tracer provider should install")
    );

    crate::policies::apply_policies(&cfg);
    trace("tests.otel.span", || {});

    settle_otel_exports();
    super::super::traces::shutdown_tracer_provider();
    let health = crate::health::get_health_snapshot();
    let seen = collector.wait_for_path("/v1/traces", Duration::from_secs(5));
    assert!(
        seen.iter().any(|path| path == "/v1/traces"),
        "expected /v1/traces export, saw {seen:?}; health={health:?}"
    );

    reset_all_otel_state();
}
