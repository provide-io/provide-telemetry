use super::*;

use std::time::Duration;

use super::export_test_support::{
    assert_export_health_success, export_test_config, reset_all_otel_state, settle_otel_exports,
    wait_for_export_health, MockOtlpCollector,
};
use crate::testing::acquire_test_state_lock;
use crate::{get_logger, trace};

#[test]
fn apply_policies_alone_does_not_block_trace_and_log_exports_without_metrics() {
    let _guard = acquire_test_state_lock();

    reset_all_otel_state();

    let collector = MockOtlpCollector::start();
    let mut cfg = export_test_config(&collector.endpoint);
    cfg.metrics.enabled = false;
    cfg.tracing.otlp_endpoint = Some(format!("{}/v1/traces", collector.endpoint));
    let resource = super::super::resource::build_resource(&cfg);
    assert!(
        super::super::traces::install_tracer_provider(&cfg, resource.clone())
            .expect("tracer provider should install")
    );
    assert!(install_logger_provider(&cfg, resource).expect("logger provider should install"));

    crate::policies::apply_policies(&cfg);
    let logger = get_logger(Some("tests.otel.combo"));
    trace("tests.otel.span", || {
        logger.info("collector smoke via trace with runtime policies and no metrics");
    });

    settle_otel_exports();
    shutdown_logger_provider();
    super::super::traces::shutdown_tracer_provider();
    let health = wait_for_export_health(true, true, false, Duration::from_secs(5));
    assert_export_health_success(&health, true, true, false);

    reset_all_otel_state();
}

#[test]
fn apply_policies_with_metrics_exports_when_meter_shuts_down_last() {
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

    crate::policies::apply_policies(&cfg);
    let logger = get_logger(Some("tests.otel.combo"));
    trace("tests.otel.span", || {
        logger.info("collector smoke via trace with runtime policies and meter last");
    });

    settle_otel_exports();
    shutdown_logger_provider();
    super::super::traces::shutdown_tracer_provider();
    super::super::metrics::shutdown_meter_provider();
    let health = wait_for_export_health(true, true, false, Duration::from_secs(5));
    assert_export_health_success(&health, true, true, false);

    reset_all_otel_state();
}

#[test]
fn apply_policies_with_metrics_do_not_block_direct_trace_exports() {
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
        super::super::metrics::install_meter_provider(&cfg, resource)
            .expect("meter provider should install")
    );

    crate::policies::apply_policies(&cfg);
    trace("tests.otel.span", || {});

    settle_otel_exports();
    super::super::traces::shutdown_tracer_provider();
    super::super::metrics::shutdown_meter_provider();
    let health = crate::health::get_health_snapshot();
    let seen = collector.wait_for_path("/v1/traces", Duration::from_secs(5));
    assert!(
        seen.iter().any(|path| path == "/v1/traces"),
        "expected /v1/traces export, saw {seen:?}; health={health:?}"
    );

    reset_all_otel_state();
}

#[test]
fn tracer_logger_and_meter_export_when_tracer_shuts_down_before_logs_and_metrics() {
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

    let logger = get_logger(Some("tests.otel.combo"));
    trace("tests.otel.span", || {
        logger.info("collector smoke via trace with tracer shutdown first");
    });

    settle_otel_exports();
    super::super::traces::shutdown_tracer_provider();
    shutdown_logger_provider();
    super::super::metrics::shutdown_meter_provider();
    let health = wait_for_export_health(true, true, false, Duration::from_secs(5));
    assert_export_health_success(&health, true, true, false);

    reset_all_otel_state();
}

#[test]
fn apply_policies_alone_does_not_block_trace_and_log_exports() {
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

    crate::policies::apply_policies(&cfg);
    let logger = get_logger(Some("tests.otel.combo"));
    trace("tests.otel.span", || {
        logger.info("collector smoke via trace with runtime policies");
    });

    settle_otel_exports();
    shutdown_logger_provider();
    super::super::metrics::shutdown_meter_provider();
    super::super::traces::shutdown_tracer_provider();
    let health = wait_for_export_health(true, true, false, Duration::from_secs(5));
    assert_export_health_success(&health, true, true, false);

    reset_all_otel_state();
}
