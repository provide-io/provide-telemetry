// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use hmac::{Hmac, Mac};
use sha2::{Digest, Sha256};
use std::fmt::Write;
use std::sync::{Mutex, OnceLock};
use uuid::Uuid;

type HmacSha256 = Hmac<Sha256>;

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

#[derive(Clone, Debug, PartialEq, Eq)]
struct ReceiptConfig {
    enabled: bool,
    signing_key: Option<String>,
    service_name: String,
    test_mode: bool,
}

impl Default for ReceiptConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            signing_key: None,
            service_name: "unknown".to_string(),
            test_mode: false,
        }
    }
}

static CONFIG: OnceLock<Mutex<ReceiptConfig>> = OnceLock::new();
static RECEIPTS: OnceLock<Mutex<Vec<RedactionReceipt>>> = OnceLock::new();

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only swap in Mutex::default().
fn default_receipt_config_mutex() -> Mutex<ReceiptConfig> {
    Mutex::new(ReceiptConfig::default())
}

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only rewrite Vec::new() syntax.
fn empty_receipts_mutex() -> Mutex<Vec<RedactionReceipt>> {
    Mutex::new(Vec::new())
}

fn config() -> &'static Mutex<ReceiptConfig> {
    CONFIG.get_or_init(default_receipt_config_mutex)
}

fn receipts() -> &'static Mutex<Vec<RedactionReceipt>> {
    RECEIPTS.get_or_init(empty_receipts_mutex)
}

fn bytes_to_hex(bytes: &[u8]) -> String {
    let mut hex = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        write!(&mut hex, "{byte:02x}").expect("writing to string cannot fail");
    }
    hex
}

pub fn enable_receipts(enabled: bool, signing_key: Option<&str>, service_name: Option<&str>) {
    let test_mode = crate::_lock::lock(config()).test_mode;
    *crate::_lock::lock(config()) = ReceiptConfig {
        enabled,
        signing_key: signing_key.map(str::to_string),
        service_name: service_name.unwrap_or("unknown").to_string(),
        test_mode,
    };
}

pub fn emit_receipt(field_path: &str, action: &str, original_value: &str) {
    let snapshot = crate::_lock::lock(config()).clone();
    if !snapshot.enabled {
        return;
    }

    let original_hash = {
        let mut hasher = Sha256::new();
        hasher.update(original_value.as_bytes());
        bytes_to_hex(&hasher.finalize())
    };
    let receipt_id = Uuid::new_v4().to_string();
    let timestamp = format!("{:?}", std::time::SystemTime::now());
    let hmac = snapshot.signing_key.as_ref().map(|key| {
        let payload = format!(
            "{}|{}|{}|{}|{}",
            receipt_id, timestamp, field_path, action, original_hash
        );
        let mut mac = HmacSha256::new_from_slice(key.as_bytes()).expect("valid HMAC key");
        mac.update(payload.as_bytes());
        bytes_to_hex(&mac.finalize().into_bytes())
    });

    let receipt = RedactionReceipt {
        receipt_id,
        timestamp,
        service_name: snapshot.service_name,
        field_path: field_path.to_string(),
        action: action.to_string(),
        original_hash,
        hmac,
    };

    if snapshot.test_mode {
        crate::_lock::lock(receipts()).push(receipt);
    }
}

pub fn get_emitted_receipts_for_tests() -> Vec<RedactionReceipt> {
    crate::_lock::lock(receipts()).clone()
}

pub fn reset_receipts_for_tests() {
    *crate::_lock::lock(config()) = ReceiptConfig {
        test_mode: true,
        ..ReceiptConfig::default()
    };
    crate::_lock::lock(receipts()).clear();
}

#[cfg(test)]
#[path = "receipts_tests.rs"]
mod tests;
