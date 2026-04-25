use super::*;

#[test]
fn receipts_test_emit_is_ignored_when_not_in_test_mode() {
    let _guard = crate::testing::acquire_test_state_lock();
    *crate::_lock::lock(config()) = ReceiptConfig::default();
    crate::_lock::lock(receipts()).clear();
    enable_receipts(true, Some("signing-key"), Some("svc"));
    emit_receipt("payload.secret", "redact", "value");

    assert!(get_emitted_receipts_for_tests().is_empty());

    enable_receipts(false, None, None);
    reset_receipts_for_tests();
}

#[test]
fn receipts_test_emit_captures_unsigned_and_signed_receipts_in_test_mode() {
    let _guard = crate::testing::acquire_test_state_lock();
    reset_receipts_for_tests();

    enable_receipts(true, None, Some("svc"));
    emit_receipt("payload.secret", "redact", "value");

    let receipts = get_emitted_receipts_for_tests();
    assert_eq!(receipts.len(), 1);
    assert_eq!(receipts[0].service_name, "svc");
    assert!(receipts[0].hmac.is_none());

    reset_receipts_for_tests();
    enable_receipts(true, Some("signing-key"), Some("svc"));
    emit_receipt("payload.secret", "redact", "value");

    let receipts = get_emitted_receipts_for_tests();
    assert_eq!(receipts.len(), 1);
    assert_eq!(receipts[0].service_name, "svc");
    assert!(receipts[0]
        .hmac
        .as_ref()
        .is_some_and(|hmac| !hmac.is_empty()));

    enable_receipts(false, None, None);
    reset_receipts_for_tests();
}
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
