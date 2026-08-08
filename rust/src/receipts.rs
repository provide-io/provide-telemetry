// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Cryptographic redaction receipts.
//!
//! This module owns two cross-language governance contracts:
//!
//! * **Canonicalization** — the hashed form of a redacted value is its RFC 8785
//!   (JCS) serialization, not its `Display` text. Hashing the rendered form
//!   collides across types: the number `1` and the string `"1"` produce the same
//!   digest, so a receipt built on them cannot distinguish the two.
//! * **Signing** — `receipt_id|timestamp|field_path|action|original_hash` under
//!   HMAC-SHA256, lowercase hex.
//!
//! Both are pinned by `spec/receipt_fixtures.yaml`, whose vectors came from
//! independent implementations (`rfc8785` and Python's `hmac`), so reproducing
//! them means agreeing with the other SDKs rather than with ourselves.

use std::collections::VecDeque;
use std::sync::{Arc, Mutex, OnceLock};

use hmac::{Hmac, Mac};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fmt::Write;
use uuid::Uuid;

use crate::errors::ConfigurationError;
pub use crate::jcs::{canonical_json, canonical_number};

type HmacSha256 = Hmac<Sha256>;

/// An immutable audit record for a single redaction event.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RedactionReceipt {
    pub receipt_id: String,
    pub timestamp: String,
    pub service_name: String,
    pub field_path: String,
    pub action: String,
    pub original_hash: String,
    pub hmac: Option<String>,
}

/// Destination for governance receipts.
///
/// `emit` returns false to reject a receipt; returning false and panicking both
/// count into `receipt_failures`. Implementations must not log — see
/// [`emit_receipt`].
pub trait ReceiptSink: Send + Sync {
    fn emit(&self, receipt: &RedactionReceipt) -> bool;
}

/// Retention cap for [`TestReceiptCollector`].
pub const TEST_RECEIPT_CAPACITY: usize = 1024;

/// In-memory sink for tests, bounded at [`TEST_RECEIPT_CAPACITY`] receipts.
///
/// Only the test collector is capped. A production sink is the caller's own
/// durable destination, and silently discarding audit records to stay inside a
/// memory budget is not a decision this library gets to make for them.
#[derive(Debug, Default)]
pub struct TestReceiptCollector {
    receipts: Mutex<VecDeque<RedactionReceipt>>,
}

impl TestReceiptCollector {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn receipts(&self) -> Vec<RedactionReceipt> {
        crate::_lock::lock(&self.receipts).iter().cloned().collect()
    }

    pub fn clear(&self) {
        crate::_lock::lock(&self.receipts).clear();
    }
}

impl ReceiptSink for TestReceiptCollector {
    fn emit(&self, receipt: &RedactionReceipt) -> bool {
        let mut receipts = crate::_lock::lock(&self.receipts);
        if receipts.len() == TEST_RECEIPT_CAPACITY {
            receipts.pop_front();
        }
        receipts.push_back(receipt.clone());
        true
    }
}

/// The inputs to [`sign_receipt`] a caller pins rather than generates. Every
/// identity-bearing field is a parameter so the fixture vectors can be
/// reproduced exactly.
pub struct SignReceiptOptions<'a> {
    pub receipt_id: &'a str,
    pub timestamp: &'a str,
    pub field_path: &'a str,
    pub action: &'a str,
    pub service_name: &'a str,
    /// Signing key. `None` leaves `hmac` empty — an unsigned receipt.
    pub key: Option<&'a [u8]>,
}

fn bytes_to_hex(bytes: &[u8]) -> String {
    let mut hex = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        write!(&mut hex, "{byte:02x}").expect("writing to string cannot fail");
    }
    hex
}

/// The canonical receipt payload, in the byte order every SDK signs.
pub fn receipt_payload(receipt: &RedactionReceipt) -> String {
    format!(
        "{}|{}|{}|{}|{}",
        receipt.receipt_id,
        receipt.timestamp,
        receipt.field_path,
        receipt.action,
        receipt.original_hash
    )
}

/// Build a receipt over `input`, canonicalizing and signing it.
pub fn sign_receipt(input: &Value, options: SignReceiptOptions<'_>) -> RedactionReceipt {
    let mut hasher = Sha256::new();
    hasher.update(canonical_json(input).as_bytes());
    let mut receipt = RedactionReceipt {
        receipt_id: options.receipt_id.to_string(),
        timestamp: options.timestamp.to_string(),
        service_name: options.service_name.to_string(),
        field_path: options.field_path.to_string(),
        action: options.action.to_string(),
        original_hash: bytes_to_hex(&hasher.finalize()),
        hmac: None,
    };
    receipt.hmac = options.key.map(|key| {
        let mut mac = HmacSha256::new_from_slice(key).expect("HMAC accepts a key of any length");
        mac.update(receipt_payload(&receipt).as_bytes());
        bytes_to_hex(&mac.finalize().into_bytes())
    });
    receipt
}

/// Hand a receipt to its sink, counting refusals.
///
/// This path must never log. The logger is what produces redactions, redactions
/// are what produce receipts, and a sink that fails on every receipt would then
/// drive an unbounded log -> receipt -> log cycle. A rejection is therefore
/// recorded only as a counter, which `get_health_snapshot().receipt_failures`
/// exposes.
pub fn emit_receipt(receipt: &RedactionReceipt, sink: &dyn ReceiptSink) {
    let accepted = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| sink.emit(receipt)))
        .unwrap_or(false);
    if !accepted {
        crate::health::increment_receipt_failures();
    }
}

#[derive(Clone, Default)]
struct ReceiptConfig {
    enabled: bool,
    signing_key: Option<String>,
    service_name: Option<String>,
    sink: Option<Arc<dyn ReceiptSink>>,
    test_mode: bool,
}

/// Options for [`enable_receipts`].
#[derive(Clone, Default)]
pub struct ReceiptOptions {
    pub enabled: bool,
    pub signing_key: Option<String>,
    pub service_name: Option<String>,
    /// Required outside test mode: where accepted receipts are delivered.
    pub sink: Option<Arc<dyn ReceiptSink>>,
}

const DEFAULT_SERVICE_NAME: &str = "unknown";

static CONFIG: OnceLock<Mutex<ReceiptConfig>> = OnceLock::new();
static TEST_COLLECTOR: OnceLock<TestReceiptCollector> = OnceLock::new();

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only swap in Mutex::default().
fn default_receipt_config_mutex() -> Mutex<ReceiptConfig> {
    Mutex::new(ReceiptConfig::default())
}

fn config() -> &'static Mutex<ReceiptConfig> {
    CONFIG.get_or_init(default_receipt_config_mutex)
}

fn test_collector() -> &'static TestReceiptCollector {
    TEST_COLLECTOR.get_or_init(TestReceiptCollector::new)
}

/// Enable or disable receipt generation.
///
/// Enabling receipts outside test mode without a sink is an error. The
/// alternative — computing and signing a full receipt for every redaction and
/// then dropping it — lets a service believe it has an audit trail when it has
/// none, which is worse than having no receipts at all.
pub fn enable_receipts(options: ReceiptOptions) -> Result<(), ConfigurationError> {
    let mut current = crate::_lock::lock(config());
    if options.enabled && !current.test_mode && options.sink.is_none() {
        return Err(ConfigurationError::new(
            "receipts are enabled but no ReceiptSink is configured; generated receipts \
             would be signed and then discarded. Pass a sink, or disable receipts.",
        ));
    }
    *current = ReceiptConfig {
        enabled: options.enabled,
        signing_key: options.signing_key,
        service_name: options.service_name,
        sink: options.sink,
        test_mode: current.test_mode,
    };
    Ok(())
}

/// Record one redaction: the hook `pii.rs` calls for every masked field.
pub(crate) fn record_redaction(field_path: &str, action: &str, original_value: &Value) {
    let snapshot = crate::_lock::lock(config()).clone();
    if !snapshot.enabled {
        return;
    }
    let receipt = sign_receipt(
        original_value,
        SignReceiptOptions {
            receipt_id: &Uuid::new_v4().to_string(),
            timestamp: &crate::logger::now_iso8601(),
            field_path,
            action,
            service_name: snapshot
                .service_name
                .as_deref()
                .unwrap_or(DEFAULT_SERVICE_NAME),
            key: snapshot.signing_key.as_ref().map(|key| key.as_bytes()),
        },
    );
    // In test mode the built-in collector stands in for a configured sink, so
    // the suite never exercises the un-sinked path `enable_receipts` rejects.
    match snapshot.sink {
        Some(sink) => emit_receipt(&receipt, sink.as_ref()),
        None => emit_receipt(&receipt, test_collector()),
    }
}

pub fn get_emitted_receipts_for_tests() -> Vec<RedactionReceipt> {
    test_collector().receipts()
}

pub fn reset_receipts_for_tests() {
    *crate::_lock::lock(config()) = ReceiptConfig {
        test_mode: true,
        ..ReceiptConfig::default()
    };
    test_collector().clear();
}

/// Leave test mode, so `enable_receipts` demands a sink the way it does in a
/// deployed service.
pub fn _set_test_mode_for_tests(test_mode: bool) {
    crate::_lock::lock(config()).test_mode = test_mode;
}

#[cfg(test)]
#[path = "receipts_tests.rs"]
mod tests;
