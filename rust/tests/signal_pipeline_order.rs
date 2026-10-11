// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Canonical signal pipeline order — `spec/pipeline_fixtures.yaml`.
//!
//! Every exit path through the pipeline is a subsequence of the canonical stage
//! order: a stage may be skipped, but two stages may never swap places, and the
//! backpressure ticket is accounted for on every path including rejections. A
//! path that refuses an event and forgets its ticket leaks queue capacity until
//! the process restarts.
//!
//! The stages are observed on the *real* logger, not through a mock pipeline
//! built for the test. The gates, the backend bridge and the bookkeeping report
//! through the SDK's stage hook as they run; the payload stages are read off the
//! marks they actually leave — a bounded value, a redacted field, a collected
//! receipt, a rendered line — at the moment the first post-sink stage reports,
//! so their position in the sequence is where they really happened. Every
//! fixture case is compared whole, release included.

use std::collections::BTreeMap;
use std::sync::Mutex;

use provide_telemetry::testing::{
    acquire_test_state_lock, reset_telemetry_state, set_pipeline_stage_hook,
};
use provide_telemetry::{
    configure_logging, enable_receipts, get_emitted_receipts_for_tests, get_health_snapshot,
    get_logger, reconfigure_telemetry, release, reset_logging_config_for_tests, set_consent_level,
    set_queue_policy, set_sampling_policy, take_json_capture, try_acquire, ConsentLevel, Logger,
    LoggingConfig, QueuePolicy, ReceiptOptions, SamplingPolicy, SecurityConfig, Signal,
    TelemetryConfig,
};
use serde::Deserialize;
use serde_json::json;

#[derive(Debug, Deserialize)]
struct PipelineCase {
    id: String,
    expected: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct Fixture {
    events: Vec<String>,
    cases: Vec<PipelineCase>,
}

fn fixture() -> Fixture {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../spec/pipeline_fixtures.yaml"
    );
    let text =
        std::fs::read_to_string(path).expect("spec/pipeline_fixtures.yaml should be readable");
    serde_yaml::from_str(&text).expect("spec/pipeline_fixtures.yaml should parse")
}

fn expected(case_id: &str) -> Vec<String> {
    fixture()
        .cases
        .into_iter()
        .find(|case| case.id == case_id)
        .unwrap_or_else(|| panic!("fixture should carry case {case_id}"))
        .expected
}

#[test]
fn every_exit_path_is_a_subsequence_of_the_canonical_order() {
    let fixture = fixture();
    for case in &fixture.cases {
        let ordered: Vec<&String> = fixture
            .events
            .iter()
            .filter(|event| case.expected.contains(event))
            .collect();
        let expected: Vec<&String> = case.expected.iter().collect();
        assert_eq!(
            ordered, expected,
            "{} reorders the canonical stages",
            case.id
        );
    }
}

/// Whatever admission control decides, the ticket is accounted for exactly
/// once. Twice would double-free capacity; never would leak it.
#[test]
fn every_exit_path_accounts_for_its_ticket_exactly_once() {
    for case in fixture().cases {
        let releases = case
            .expected
            .iter()
            .filter(|event| *event == "release")
            .count();
        assert_eq!(releases, 1, "{} does not release exactly once", case.id);
    }
}

/// Every fixture case must be run by one of the tests below; a case added to
/// the fixture without a run here fails rather than passing unexercised.
#[test]
fn every_fixture_case_is_exercised() {
    let mut ran = vec![
        "consent_rejection",
        "sampling_rejection",
        "queue_rejection",
        "local_only_success",
    ];
    if cfg!(feature = "otel") {
        ran.extend(["backend_success", "backend_failure"]);
    } else {
        return;
    }
    let mut ids: Vec<String> = fixture().cases.into_iter().map(|case| case.id).collect();
    ids.sort();
    ran.sort_unstable();
    assert_eq!(ids, ran);
}

static OBSERVED: Mutex<Vec<String>> = Mutex::new(Vec::new());

fn observed() -> std::sync::MutexGuard<'static, Vec<String>> {
    OBSERVED.lock().unwrap_or_else(|e| e.into_inner())
}

/// Read the payload marks left on the probe record. Runs from inside the hook
/// on the first stage after the local sinks, so the marks land in the sequence
/// at the point the record reached its sinks.
fn push_payload_marks(stages: &mut Vec<String>) {
    // The rendered line rather than the fallback buffer: the buffer is filled
    // after the backend bridge has run, the line before it.
    let rendered = String::from_utf8(take_json_capture()).expect("capture should be utf8");
    if rendered.contains(r#""deep":{"a":"***"}"#) {
        stages.push("hardening".to_string());
    }
    if rendered.contains(r#""password":"***""#) && !rendered.contains("s3cr3t") {
        stages.push("pii".to_string());
    }
    if !get_emitted_receipts_for_tests().is_empty() {
        stages.push("receipt".to_string());
    }
    if rendered.contains("pipeline.probe") {
        stages.push("local".to_string());
    }
}

fn record_stage(stage: &'static str) {
    let mut stages = observed();
    let admitted = stages.iter().any(|seen| seen == "backpressure")
        && !stages
            .iter()
            .any(|seen| seen == "backend" || seen == "health");
    if admitted && (stage == "backend" || stage == "health") {
        push_payload_marks(&mut stages);
    }
    // Health counts the record only after every sink has run.
    let health_seen = stage == "health" || stages.iter().any(|seen| seen == "health");
    if !health_seen && get_health_snapshot().emitted_logs != 0 {
        stages.push(format!("health-before-{stage}"));
    }
    stages.push(stage.to_string());
}

fn pipeline_config() -> TelemetryConfig {
    TelemetryConfig {
        service_name: "pipeline-svc".to_string(),
        security: SecurityConfig {
            max_attr_value_length: 1024,
            max_attr_count: 64,
            max_nesting_depth: 2,
        },
        ..TelemetryConfig::default()
    }
}

/// Emit one record through the real logger and report the stages it passed.
///
/// The record carries a structure deeper than the configured ceiling and a
/// sensitive key, so hardening and PII each mark the same input distinguishably.
fn observe_stages(install: impl FnOnce(), configure_gates: impl FnOnce()) -> Vec<String> {
    reset_telemetry_state();
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    install();
    configure_logging(LoggingConfig {
        level: "TRACE".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        ..LoggingConfig::default()
    });
    enable_receipts(ReceiptOptions {
        enabled: true,
        service_name: Some("pipeline-svc".to_string()),
        ..ReceiptOptions::default()
    })
    .expect("test mode collects without a configured sink");
    // Gates are configured after the runtime config installs its defaults,
    // which would otherwise overwrite them.
    set_queue_policy(QueuePolicy {
        logs_maxsize: 1,
        ..QueuePolicy::default()
    });
    configure_gates();
    provide_telemetry::enable_json_capture_for_tests();
    // Last, so every counter read in the hook is this record's alone.
    provide_telemetry::health::_reset_health_for_tests();

    let mut fields = BTreeMap::new();
    fields.insert("deep".to_string(), json!({ "a": { "b": "unreachable" } }));
    fields.insert("password".to_string(), json!("s3cr3t"));

    observed().clear();
    set_pipeline_stage_hook(Some(record_stage));
    get_logger(Some("tests.pipeline")).log_fields("INFO", "pipeline.probe", &fields);
    set_pipeline_stage_hook(None);
    std::mem::take(&mut *observed())
}

fn runtime_only() {
    reconfigure_telemetry(Some(pipeline_config())).expect("runtime config should install");
}

fn no_gates() {}

/// True when a fresh ticket can still be taken from a single-slot queue.
fn ticket_is_available() -> bool {
    match try_acquire(Signal::Logs) {
        Some(ticket) => {
            release(ticket);
            true
        }
        None => false,
    }
}

#[test]
fn local_only_success_matches_the_fixture() {
    let _guard = acquire_test_state_lock();

    let observed = observe_stages(runtime_only, no_gates);

    assert_eq!(observed, expected("local_only_success"));
    assert_eq!(get_health_snapshot().emitted_logs, 1);
    assert!(ticket_is_available(), "the ticket must be released");
    reset_telemetry_state();
}

#[test]
fn consent_rejection_matches_the_fixture_and_counts_a_drop() {
    let _guard = acquire_test_state_lock();

    let observed = observe_stages(runtime_only, || set_consent_level(ConsentLevel::None));

    assert_eq!(observed, expected("consent_rejection"));
    let health = get_health_snapshot();
    assert_eq!((health.emitted_logs, health.dropped_logs), (0, 1));
    assert!(ticket_is_available());
    reset_telemetry_state();
}

#[test]
fn sampling_rejection_matches_the_fixture() {
    let _guard = acquire_test_state_lock();

    let observed = observe_stages(runtime_only, || {
        set_sampling_policy(
            Signal::Logs,
            SamplingPolicy {
                default_rate: 0.0,
                overrides: BTreeMap::new(),
            },
        )
        .expect("logs is a valid signal");
    });

    assert_eq!(observed, expected("sampling_rejection"));
    assert_eq!(get_health_snapshot().dropped_logs, 1);
    assert!(ticket_is_available());
    reset_telemetry_state();
}

/// A record refused by backpressure must not consume the slot it was refused:
/// with one ticket outstanding the queue is full and stays full.
#[test]
fn queue_rejection_matches_the_fixture_and_leaks_no_capacity() {
    let _guard = acquire_test_state_lock();
    let mut held = None;

    let observed = observe_stages(runtime_only, || held = try_acquire(Signal::Logs));

    assert!(held.is_some(), "the test must hold the only slot");
    assert_eq!(observed, expected("queue_rejection"));
    assert_eq!(get_health_snapshot().dropped_logs, 1);
    assert!(!ticket_is_available(), "the refused record took the slot");

    release(held.expect("held above"));
    assert!(ticket_is_available());
    reset_telemetry_state();
}

#[cfg(feature = "otel")]
mod backend {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Arc;
    use std::time::Duration;

    use provide_telemetry::setup_telemetry;

    /// A collector that accepts every export, until dropped.
    struct AcceptingCollector {
        endpoint: String,
        stopping: Arc<AtomicBool>,
    }

    impl AcceptingCollector {
        fn start() -> Self {
            let listener = TcpListener::bind("127.0.0.1:0").expect("bind collector");
            listener.set_nonblocking(true).expect("nonblocking");
            let endpoint = format!("http://{}/v1/logs", listener.local_addr().expect("addr"));
            let stopping = Arc::new(AtomicBool::new(false));
            let worker_stopping = Arc::clone(&stopping);
            std::thread::spawn(move || {
                while !worker_stopping.load(Ordering::Relaxed) {
                    let Ok((mut stream, _)) = listener.accept() else {
                        std::thread::sleep(Duration::from_millis(5));
                        continue;
                    };
                    let _ = stream.set_nonblocking(false);
                    let _ = stream.set_read_timeout(Some(Duration::from_millis(200)));
                    let mut buf = [0_u8; 8192];
                    let _ = stream.read(&mut buf);
                    let _ = stream.write_all(
                        b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                    );
                }
            });
            Self { endpoint, stopping }
        }
    }

    impl Drop for AcceptingCollector {
        fn drop(&mut self) {
            self.stopping.store(true, Ordering::Relaxed);
        }
    }

    /// An endpoint nothing listens on: every export is refused.
    fn refusing_endpoint() -> String {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let addr = listener.local_addr().expect("addr");
        drop(listener);
        format!("http://{addr}/v1/logs")
    }

    fn install_backend(endpoint: String) {
        let mut cfg = pipeline_config();
        cfg.tracing.enabled = false;
        cfg.metrics.enabled = false;
        cfg.logging.otlp_endpoint = Some(endpoint);
        cfg.exporter.logs_timeout_seconds = 1.0;
        setup_telemetry(Some(cfg)).expect("setup should install the log provider");
    }

    #[test]
    fn backend_success_matches_the_fixture() {
        let _guard = acquire_test_state_lock();
        let collector = AcceptingCollector::start();

        let endpoint = collector.endpoint.clone();
        let observed = observe_stages(move || install_backend(endpoint), no_gates);

        assert_eq!(observed, expected("backend_success"));
        assert!(ticket_is_available(), "the ticket must be released");
        reset_telemetry_state();
    }

    /// The bridge hands the record to the OTLP batch processor and returns:
    /// the refusal arrives later, on the export thread, as an export failure.
    /// The pipeline's own stages are the fixture's either way.
    #[test]
    fn backend_failure_matches_the_fixture() {
        let _guard = acquire_test_state_lock();

        let observed = observe_stages(|| install_backend(refusing_endpoint()), no_gates);

        assert_eq!(observed, expected("backend_failure"));
        assert!(ticket_is_available(), "a refused export kept its ticket");
        reset_telemetry_state();
    }
}
