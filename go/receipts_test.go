// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

package telemetry

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"strings"
	"testing"
)

// resetReceipts resets receipt state and registers cleanup for t.
func resetReceipts(t *testing.T) {
	t.Helper()
	_resetPIIRules()
	ResetReceiptsForTests()
	t.Cleanup(func() {
		_resetPIIRules()
		ResetReceiptsForTests()
	})
}

// TestReceiptsDisabledByDefault verifies no receipts are emitted before EnableReceipts is called.
func TestReceiptsDisabledByDefault(t *testing.T) {
	resetReceipts(t)
	payload := map[string]any{"password": "secret123"}
	SanitizePayload(payload, true, 0)
	receipts := GetEmittedReceiptsForTests()
	if len(receipts) != 0 {
		t.Errorf("expected 0 receipts, got %d", len(receipts))
	}
}

// TestReceiptsEmittedWhenEnabled verifies receipts are generated after EnableReceipts.
func TestReceiptsEmittedWhenEnabled(t *testing.T) {
	resetReceipts(t)
	EnableReceipts(true, "", "test-svc")
	payload := map[string]any{"password": "secret123"}
	SanitizePayload(payload, true, 0)
	receipts := GetEmittedReceiptsForTests()
	if len(receipts) != 1 {
		t.Fatalf("expected 1 receipt, got %d", len(receipts))
	}
	r := receipts[0]
	if r.FieldPath != "password" {
		t.Errorf("expected field_path 'password', got %q", r.FieldPath)
	}
	if r.Action != "redact" {
		t.Errorf("expected action 'redact', got %q", r.Action)
	}
	if r.ReceiptID == "" {
		t.Error("expected non-empty receipt_id")
	}
}

// TestReceiptOriginalHashIsSHA256 verifies the hash is SHA-256 of the original value.
func TestReceiptOriginalHashIsSHA256(t *testing.T) {
	resetReceipts(t)
	EnableReceipts(true, "", "")
	payload := map[string]any{"password": "secret123"}
	SanitizePayload(payload, true, 0)
	receipts := GetEmittedReceiptsForTests()
	if len(receipts) != 1 {
		t.Fatalf("expected 1 receipt, got %d", len(receipts))
	}
	sum := sha256.Sum256([]byte(fmt.Sprintf("%v", "secret123")))
	expected := hex.EncodeToString(sum[:])
	if receipts[0].OriginalHash != expected {
		t.Errorf("hash mismatch: expected %q, got %q", expected, receipts[0].OriginalHash)
	}
}

// TestReceiptHMACWhenKeyProvided verifies HMAC is computed correctly when a key is set.
func TestReceiptHMACWhenKeyProvided(t *testing.T) {
	resetReceipts(t)
	EnableReceipts(true, "test-key", "")
	payload := map[string]any{"password": "secret123"}
	SanitizePayload(payload, true, 0)
	receipts := GetEmittedReceiptsForTests()
	if len(receipts) != 1 {
		t.Fatalf("expected 1 receipt, got %d", len(receipts))
	}
	r := receipts[0]
	if r.HMAC == "" {
		t.Error("expected non-empty HMAC")
	}
	payloadStr := fmt.Sprintf("%s|%s|%s|%s|%s",
		r.ReceiptID, r.Timestamp, r.FieldPath, r.Action, r.OriginalHash)
	mac := hmac.New(sha256.New, []byte("test-key"))
	mac.Write([]byte(payloadStr)) //nolint:errcheck
	expected := hex.EncodeToString(mac.Sum(nil))
	if r.HMAC != expected {
		t.Errorf("HMAC mismatch: expected %q, got %q", expected, r.HMAC)
	}
}

// TestReceiptHMACEmptyWhenNoKey verifies HMAC is empty when no signing key is provided.
func TestReceiptHMACEmptyWhenNoKey(t *testing.T) {
	resetReceipts(t)
	EnableReceipts(true, "", "")
	payload := map[string]any{"password": "secret123"}
	SanitizePayload(payload, true, 0)
	receipts := GetEmittedReceiptsForTests()
	if len(receipts) != 1 {
		t.Fatalf("expected 1 receipt, got %d", len(receipts))
	}
	if receipts[0].HMAC != "" {
		t.Errorf("expected empty HMAC, got %q", receipts[0].HMAC)
	}
}

// TestReceiptTamperDetection verifies that changing field_path produces a different HMAC.
func TestReceiptTamperDetection(t *testing.T) {
	resetReceipts(t)
	EnableReceipts(true, "test-key", "")
	payload := map[string]any{"password": "secret123"}
	SanitizePayload(payload, true, 0)
	receipts := GetEmittedReceiptsForTests()
	if len(receipts) != 1 {
		t.Fatalf("expected 1 receipt, got %d", len(receipts))
	}
	r := receipts[0]
	tamperedPayload := fmt.Sprintf("%s|%s|%s|%s|%s",
		r.ReceiptID, r.Timestamp, "tampered.path", r.Action, r.OriginalHash)
	mac := hmac.New(sha256.New, []byte("test-key"))
	mac.Write([]byte(tamperedPayload)) //nolint:errcheck
	tamperedHMAC := hex.EncodeToString(mac.Sum(nil))
	if r.HMAC == tamperedHMAC {
		t.Error("expected HMAC to differ after tampering with field_path")
	}
}

// TestEnableReceiptsDisabled verifies that EnableReceipts(false,...) unregisters the hook.
func TestEnableReceiptsDisabled(t *testing.T) {
	resetReceipts(t)
	EnableReceipts(true, "", "")
	_piiMu.RLock()
	hook := _receiptHook
	_piiMu.RUnlock()
	if hook == nil {
		t.Error("expected hook to be set after EnableReceipts(true)")
	}
	EnableReceipts(false, "", "")
	_piiMu.RLock()
	hook = _receiptHook
	_piiMu.RUnlock()
	if hook != nil {
		t.Error("expected hook to be nil after EnableReceipts(false)")
	}
}

// TestReceiptIDIsUUIDFormat verifies receipt_id has UUID format.
func TestReceiptIDIsUUIDFormat(t *testing.T) {
	resetReceipts(t)
	EnableReceipts(true, "", "")
	payload := map[string]any{"password": "secret123"}
	SanitizePayload(payload, true, 0)
	receipts := GetEmittedReceiptsForTests()
	if len(receipts) != 1 {
		t.Fatalf("expected 1 receipt, got %d", len(receipts))
	}
	rid := receipts[0].ReceiptID
	if len(rid) != 36 {
		t.Errorf("expected UUID length 36, got %d", len(rid))
	}
	parts := strings.Split(rid, "-")
	if len(parts) != 5 {
		t.Errorf("expected 5 UUID parts, got %d", len(parts))
	}
}

// TestReceiptsProductionMode verifies production mode logs rather than stores.
func TestReceiptsProductionMode(t *testing.T) {
	t.Cleanup(func() {
		_resetPIIRules()
		ResetReceiptsForTests()
	})
	_resetPIIRules()
	// Set production mode (test mode off) manually.
	_receiptsMu.Lock()
	_receiptsKey = ""
	_receiptsStore = nil
	_receiptsTestMode = false
	_receiptsMu.Unlock()
	SetReceiptHook(nil)

	EnableReceipts(true, "", "prod-svc")
	payload := map[string]any{"password": "secret123"}
	SanitizePayload(payload, true, 0)
	// In production mode, receipts are logged, not stored.
	_receiptsMu.RLock()
	n := len(_receiptsStore)
	_receiptsMu.RUnlock()
	if n != 0 {
		t.Errorf("expected 0 stored receipts in production mode, got %d", n)
	}
	EnableReceipts(false, "", "")
}
