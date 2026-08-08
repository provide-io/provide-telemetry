use super::*;

use serde_json::json;

use crate::health::{_reset_health_for_tests, get_health_snapshot};
use crate::testing::acquire_test_state_lock;

/// A sink that refuses everything, the way a full disk or a closed connection
/// would.
struct RejectingSink;

impl ReceiptSink for RejectingSink {
    fn emit(&self, _: &RedactionReceipt) -> bool {
        false
    }
}

/// A sink that panics, the way a caller's buggy serializer would.
struct PanickingSink;

impl ReceiptSink for PanickingSink {
    fn emit(&self, _: &RedactionReceipt) -> bool {
        panic!("sink exploded");
    }
}

fn fixture_receipt() -> RedactionReceipt {
    sign_receipt(
        &json!({ "a": 1 }),
        SignReceiptOptions {
            receipt_id: "018f47a2-6b7c-7d8e-9f10-111213141516",
            timestamp: "2026-08-04T12:34:56.789Z",
            field_path: "user.profile",
            action: "redact",
            service_name: "svc",
            key: None,
        },
    )
}

#[test]
fn receipts_test_payload_is_the_pipe_joined_identity() {
    assert_eq!(
        receipt_payload(&fixture_receipt()),
        format!(
            "018f47a2-6b7c-7d8e-9f10-111213141516|2026-08-04T12:34:56.789Z|user.profile|redact|{}",
            fixture_receipt().original_hash
        )
    );
}

#[test]
fn receipts_test_signing_key_produces_a_hex_hmac() {
    let signed = sign_receipt(
        &json!({ "a": 1 }),
        SignReceiptOptions {
            receipt_id: "id",
            timestamp: "ts",
            field_path: "path",
            action: "redact",
            service_name: "svc",
            key: Some(b"parity-secret"),
        },
    );

    let hmac = signed.hmac.expect("a keyed receipt must be signed");
    assert_eq!(hmac.len(), 64);
    assert!(hmac.chars().all(|ch| ch.is_ascii_hexdigit()));
    assert!(fixture_receipt().hmac.is_none());
}

#[test]
fn receipts_test_collector_evicts_the_oldest_past_capacity() {
    let collector = TestReceiptCollector::new();
    for index in 0..=TEST_RECEIPT_CAPACITY {
        let mut receipt = fixture_receipt();
        receipt.receipt_id = index.to_string();
        assert!(collector.emit(&receipt));
    }

    let held = collector.receipts();
    assert_eq!(held.len(), TEST_RECEIPT_CAPACITY);
    // The first receipt made room for the last one, rather than the collector
    // growing without bound.
    assert_eq!(held[0].receipt_id, "1");
    assert_eq!(
        held[TEST_RECEIPT_CAPACITY - 1].receipt_id,
        TEST_RECEIPT_CAPACITY.to_string()
    );

    collector.clear();
    assert!(collector.receipts().is_empty());
}

#[test]
fn receipts_test_a_refused_receipt_is_counted_not_logged() {
    let _guard = acquire_test_state_lock();
    _reset_health_for_tests();

    emit_receipt(&fixture_receipt(), &RejectingSink);

    assert_eq!(get_health_snapshot().receipt_failures, 1);
}

/// A sink that panics must not take the caller's log call down with it — the
/// redaction has already happened, and the record still has to be emitted.
#[test]
fn receipts_test_a_panicking_sink_is_counted_and_contained() {
    let _guard = acquire_test_state_lock();
    _reset_health_for_tests();

    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(|_| {}));
    emit_receipt(&fixture_receipt(), &PanickingSink);
    std::panic::set_hook(previous);

    assert_eq!(get_health_snapshot().receipt_failures, 1);
}

#[test]
fn receipts_test_an_accepted_receipt_counts_no_failure() {
    let _guard = acquire_test_state_lock();
    _reset_health_for_tests();
    let collector = TestReceiptCollector::new();

    emit_receipt(&fixture_receipt(), &collector);

    assert_eq!(get_health_snapshot().receipt_failures, 0);
    assert_eq!(collector.receipts().len(), 1);
}

/// Enabling receipts in a deployed service without a sink is refused. The
/// previous behavior signed a receipt for every redaction and dropped it, so a
/// service could believe it had an audit trail and have none.
#[test]
fn receipts_test_production_enablement_requires_a_sink() {
    let _guard = acquire_test_state_lock();
    reset_receipts_for_tests();
    _set_test_mode_for_tests(false);

    let err = enable_receipts(ReceiptOptions {
        enabled: true,
        ..ReceiptOptions::default()
    })
    .expect_err("enabling receipts without a sink must fail");
    assert!(err.message.contains("ReceiptSink"), "{}", err.message);

    // The same call succeeds once a destination exists.
    enable_receipts(ReceiptOptions {
        enabled: true,
        sink: Some(Arc::new(TestReceiptCollector::new())),
        ..ReceiptOptions::default()
    })
    .expect("a sinked config should install");

    reset_receipts_for_tests();
}

/// Disabling receipts needs no sink: nothing will be generated to deliver.
#[test]
fn receipts_test_disabling_needs_no_sink_outside_test_mode() {
    let _guard = acquire_test_state_lock();
    reset_receipts_for_tests();
    _set_test_mode_for_tests(false);

    enable_receipts(ReceiptOptions::default()).expect("disabling must not require a sink");

    reset_receipts_for_tests();
}

#[test]
fn receipts_test_redactions_reach_the_configured_sink() {
    let _guard = acquire_test_state_lock();
    reset_receipts_for_tests();
    let collector = Arc::new(TestReceiptCollector::new());

    enable_receipts(ReceiptOptions {
        enabled: true,
        signing_key: Some("signing-key".to_string()),
        service_name: Some("svc".to_string()),
        sink: Some(collector.clone()),
    })
    .expect("receipts should enable");
    record_redaction("payload.secret", "redact", &json!("value"));

    let held = collector.receipts();
    assert_eq!(held.len(), 1);
    assert_eq!(held[0].service_name, "svc");
    assert_eq!(held[0].field_path, "payload.secret");
    assert!(held[0].hmac.is_some());
    // The configured sink took it, so the built-in collector saw nothing.
    assert!(get_emitted_receipts_for_tests().is_empty());

    reset_receipts_for_tests();
}

/// With no sink configured, test mode falls back to the built-in collector so
/// the suite never runs the path `enable_receipts` refuses.
#[test]
fn receipts_test_test_mode_collects_without_a_configured_sink() {
    let _guard = acquire_test_state_lock();
    reset_receipts_for_tests();

    enable_receipts(ReceiptOptions {
        enabled: true,
        service_name: Some("svc".to_string()),
        ..ReceiptOptions::default()
    })
    .expect("test mode needs no sink");
    record_redaction("payload.secret", "redact", &json!("value"));

    let held = get_emitted_receipts_for_tests();
    assert_eq!(held.len(), 1);
    assert_eq!(held[0].service_name, "svc");
    assert!(held[0].hmac.is_none());
    // The generated timestamp is the logger's ISO-8601 rendering, not Rust's
    // SystemTime debug text.
    assert!(held[0].timestamp.ends_with('Z'), "{}", held[0].timestamp);

    reset_receipts_for_tests();
}

#[test]
fn receipts_test_service_name_defaults_when_unset() {
    let _guard = acquire_test_state_lock();
    reset_receipts_for_tests();

    enable_receipts(ReceiptOptions {
        enabled: true,
        ..ReceiptOptions::default()
    })
    .expect("test mode needs no sink");
    record_redaction("payload.secret", "redact", &json!("value"));

    assert_eq!(
        get_emitted_receipts_for_tests()[0].service_name,
        DEFAULT_SERVICE_NAME
    );

    reset_receipts_for_tests();
}

#[test]
fn receipts_test_disabled_receipts_generate_nothing() {
    let _guard = acquire_test_state_lock();
    reset_receipts_for_tests();

    record_redaction("payload.secret", "redact", &json!("value"));

    assert!(get_emitted_receipts_for_tests().is_empty());
}
