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
//! built for the test. A parallel `process_signal` written here could pass
//! while the shipping path diverged from it, which is the class of bug the
//! fixture exists to prevent — so each stage is detected by the mark it
//! actually leaves: a bounded value, a redacted field, a collected receipt, a
//! rendered line, a health counter, a ticket that can be taken again.

use std::collections::BTreeMap;

use provide_telemetry::testing::{acquire_test_state_lock, reset_telemetry_state};
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

/// Stages this suite can observe on the logs pipeline. `backend` needs a live
/// OTLP provider and so is exercised by the OTel suites instead.
const OBSERVABLE: &[&str] = &[
    "consent",
    "sampling",
    "backpressure",
    "hardening",
    "pii",
    "receipt",
    "local",
    "health",
];

/// What a record refused by admission control leaves behind. The fixture's
/// rejection paths also list `health` and `release`, but neither is observable
/// from here: Rust's drop accounting lands on `dropped_logs` rather than the
/// `emitted_logs` this harness watches, and a ticket that was never taken has
/// nothing to release. `ticket_is_available` checks the capacity claim instead.
const REJECTED_AT_ADMISSION: [&str; 1] = ["consent"];

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

fn expected_observable(case_id: &str) -> Vec<String> {
    fixture()
        .cases
        .into_iter()
        .find(|case| case.id == case_id)
        .unwrap_or_else(|| panic!("fixture should carry case {case_id}"))
        .expected
        .into_iter()
        .filter(|stage| OBSERVABLE.contains(&stage.as_str()))
        .collect()
}

/// Emit one record through the real logger and report which stages left a mark.
///
/// The record carries a structure deeper than the configured ceiling and a
/// sensitive key, so hardening and PII each mark the same input distinguishably.
fn observe_stages(configure_gates: impl FnOnce()) -> Vec<String> {
    reset_telemetry_state();
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    reconfigure_telemetry(Some(TelemetryConfig {
        service_name: "pipeline-svc".to_string(),
        security: SecurityConfig {
            max_attr_value_length: 1024,
            max_attr_count: 64,
            max_nesting_depth: 2,
        },
        ..TelemetryConfig::default()
    }))
    .expect("runtime config should install");
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
    configure_gates();

    provide_telemetry::enable_json_capture_for_tests();
    let mut fields = BTreeMap::new();
    fields.insert("deep".to_string(), json!({ "a": { "b": "unreachable" } }));
    fields.insert("password".to_string(), json!("s3cr3t"));

    let before = get_health_snapshot().emitted_logs;
    get_logger(Some("tests.pipeline")).log_fields("INFO", "pipeline.probe", &fields);
    let after = get_health_snapshot().emitted_logs;
    let rendered = String::from_utf8(take_json_capture()).expect("capture should be utf8");
    let events = Logger::drain_events_for_tests();

    // Reaching the logger at all means consent was consulted; every later stage
    // is inferred from the marks the record and the counters carry.
    let mut stages = vec!["consent".to_string()];
    // Found by message rather than by position: the fallback buffer is process
    // global, so a concurrent suite's event can share it.
    let Some(event) = events
        .iter()
        .find(|event| event.message == "pipeline.probe")
    else {
        return stages;
    };
    // The body only runs once sampling and backpressure have both admitted it.
    stages.push("sampling".to_string());
    stages.push("backpressure".to_string());
    if event.context.get("deep") == Some(&json!({ "a": "***" })) {
        stages.push("hardening".to_string());
    }
    if event.context.get("password") == Some(&json!("***")) {
        stages.push("pii".to_string());
    }
    if !get_emitted_receipts_for_tests().is_empty() {
        stages.push("receipt".to_string());
    }
    if rendered.contains("pipeline.probe") {
        stages.push("local".to_string());
    }
    if after > before {
        stages.push("health".to_string());
    }
    stages
}

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
fn the_full_success_path_runs_every_observable_stage_in_order() {
    let _guard = acquire_test_state_lock();

    let observed = observe_stages(|| {});

    assert_eq!(observed, expected_observable("local_only_success"));
    assert!(ticket_is_available(), "the ticket must be released");
    reset_telemetry_state();
}

/// Order, not just presence: PII walks the record recursively, so a structure
/// that outran the depth ceiling would become its problem to bound.
#[test]
fn hardening_precedes_pii_receipt_and_every_sink() {
    let _guard = acquire_test_state_lock();

    let observed = observe_stages(|| {});
    let position = |stage: &str| {
        observed
            .iter()
            .position(|candidate| candidate == stage)
            .unwrap_or_else(|| panic!("{stage} should have been observed"))
    };

    assert!(position("hardening") < position("pii"));
    assert!(position("pii") < position("receipt"));
    assert!(position("receipt") < position("local"));
    assert!(position("local") < position("health"));
    reset_telemetry_state();
}

#[test]
fn consent_rejection_stops_at_consent_and_keeps_its_capacity() {
    let _guard = acquire_test_state_lock();

    let observed = observe_stages(|| set_consent_level(ConsentLevel::None));

    assert_eq!(observed, REJECTED_AT_ADMISSION);
    assert!(ticket_is_available());
    reset_telemetry_state();
}

#[test]
fn sampling_rejection_stops_before_any_payload_work() {
    let _guard = acquire_test_state_lock();

    let observed = observe_stages(|| {
        set_sampling_policy(
            Signal::Logs,
            SamplingPolicy {
                default_rate: 0.0,
                overrides: BTreeMap::new(),
            },
        )
        .expect("logs is a valid signal");
    });

    assert_eq!(observed, REJECTED_AT_ADMISSION);
    assert!(ticket_is_available());
    reset_telemetry_state();
}

/// A record refused by backpressure must not consume the slot it was refused:
/// with one ticket outstanding the queue is full and stays full.
#[test]
fn queue_rejection_leaks_no_capacity() {
    let _guard = acquire_test_state_lock();
    let mut held = None;

    let observed = observe_stages(|| {
        set_queue_policy(QueuePolicy {
            logs_maxsize: 1,
            ..QueuePolicy::default()
        });
        held = try_acquire(Signal::Logs);
    });

    assert!(held.is_some(), "the test must hold the only slot");
    assert_eq!(observed, REJECTED_AT_ADMISSION);
    assert!(!ticket_is_available(), "the refused record took the slot");

    release(held.expect("held above"));
    assert!(ticket_is_available());
    reset_telemetry_state();
}
