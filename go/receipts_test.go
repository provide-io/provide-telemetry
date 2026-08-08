// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

package telemetry

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"testing"
	"time"
)

// resetReceipts resets receipt state and registers cleanup for t.
func resetReceipts(t *testing.T) {
	t.Helper()
	_resetPIIRules()
	ResetReceiptsForTests()
	_resetHealth()
	t.Cleanup(func() {
		_resetPIIRules()
		ResetReceiptsForTests()
		_resetHealth()
	})
}

// mustEnableReceipts fails the test if the sink contract rejects opts.
func mustEnableReceipts(t *testing.T, opts ReceiptOptions) {
	t.Helper()
	if err := EnableReceipts(opts); err != nil {
		t.Fatalf("EnableReceipts(%+v): %v", opts, err)
	}
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
	mustEnableReceipts(t, ReceiptOptions{Enabled: true, ServiceName: "test-svc"})
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
	mustEnableReceipts(t, ReceiptOptions{Enabled: true})
	payload := map[string]any{"password": "secret123"}
	SanitizePayload(payload, true, 0)
	receipts := GetEmittedReceiptsForTests()
	if len(receipts) != 1 {
		t.Fatalf("expected 1 receipt, got %d", len(receipts))
	}
	// Canonical JSON, not the %v rendering: the string "1" and the number 1
	// share a display form and must not share a digest.
	sum := sha256.Sum256([]byte(`"secret123"`))
	expected := hex.EncodeToString(sum[:])
	if receipts[0].OriginalHash != expected {
		t.Errorf("hash mismatch: expected %q, got %q", expected, receipts[0].OriginalHash)
	}
}

// TestReceiptHMACWhenKeyProvided verifies HMAC is computed correctly when a key is set.
func TestReceiptHMACWhenKeyProvided(t *testing.T) {
	resetReceipts(t)
	mustEnableReceipts(t, ReceiptOptions{Enabled: true, SigningKey: "test-key"})
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
	mustEnableReceipts(t, ReceiptOptions{Enabled: true})
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
	mustEnableReceipts(t, ReceiptOptions{Enabled: true, SigningKey: "test-key"})
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
	mustEnableReceipts(t, ReceiptOptions{Enabled: true})
	_piiMu.RLock()
	hook := _receiptHook
	_piiMu.RUnlock()
	if hook == nil {
		t.Error("expected hook to be set after EnableReceipts(true)")
	}
	mustEnableReceipts(t, ReceiptOptions{})
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
	mustEnableReceipts(t, ReceiptOptions{Enabled: true})
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

// _enterProductionReceiptMode switches the receipt engine out of test mode for
// the duration of t, so the sink contract can be exercised as a caller sees it.
func _enterProductionReceiptMode(t *testing.T) {
	t.Helper()
	resetReceipts(t)
	_receiptsMu.Lock()
	_receiptsTestMode = false
	_receiptsMu.Unlock()
}

// TestReceiptsProductionMode verifies production receipts reach the configured
// sink and never the test collector.
func TestReceiptsProductionMode(t *testing.T) {
	_enterProductionReceiptMode(t)

	sink := &TestReceiptCollector{}
	mustEnableReceipts(t, ReceiptOptions{Enabled: true, ServiceName: "prod-svc", Sink: sink})
	SanitizePayload(map[string]any{"password": "secret123"}, true, 0)

	delivered := sink.Receipts()
	if len(delivered) != 1 {
		t.Fatalf("expected 1 receipt at the sink, got %d", len(delivered))
	}
	if delivered[0].ServiceName != "prod-svc" {
		t.Errorf("service name: got %q", delivered[0].ServiceName)
	}
	if collected := GetEmittedReceiptsForTests(); len(collected) != 0 {
		t.Errorf("test collector took delivery outside test mode: %d", len(collected))
	}
	if got := GetHealthSnapshot().ReceiptFailures; got != 0 {
		t.Errorf("ReceiptFailures: want 0, got %d", got)
	}
}

// TestEnableReceiptsRequiresSinkInProduction pins the contract that enabling
// receipts without a destination is an error, not a silent discard: a service
// would otherwise sign an audit record per redaction and drop every one.
func TestEnableReceiptsRequiresSinkInProduction(t *testing.T) {
	_enterProductionReceiptMode(t)

	if err := EnableReceipts(ReceiptOptions{Enabled: true, SigningKey: "k"}); !errors.Is(err, ErrMissingReceiptSink) {
		t.Fatalf("want ErrMissingReceiptSink, got %v", err)
	}
	_piiMu.RLock()
	hook := _receiptHook
	_piiMu.RUnlock()
	if hook != nil {
		t.Error("a rejected EnableReceipts must not register the hook")
	}
	// Disabling never needs a sink.
	if err := EnableReceipts(ReceiptOptions{}); err != nil {
		t.Fatalf("disabling receipts: %v", err)
	}
}

type _rejectingSink struct{}

func (_rejectingSink) Emit(RedactionReceipt) bool { return false }

type _panickingSink struct{}

func (_panickingSink) Emit(RedactionReceipt) bool { panic("sink exploded") }

// TestReceiptSinkFailuresCountIntoHealth covers the three ways a receipt fails
// to arrive. All three are counted and none of them logs: the logger is what
// produces redactions, so logging here would be an unbounded cycle.
func TestReceiptSinkFailuresCountIntoHealth(t *testing.T) {
	cases := []struct {
		name string
		sink ReceiptSink
	}{
		{"refusing sink", _rejectingSink{}},
		{"panicking sink", _panickingSink{}},
		{"absent sink", nil},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			resetReceipts(t)
			emitReceipt(RedactionReceipt{ReceiptID: "r"}, tc.sink)
			if got := GetHealthSnapshot().ReceiptFailures; got != 1 {
				t.Fatalf("ReceiptFailures: want 1, got %d", got)
			}
		})
	}
}

// TestTestReceiptCollectorEvictsOldest pins the cap on the one sink this
// library owns. A production sink is never capped.
func TestTestReceiptCollectorEvictsOldest(t *testing.T) {
	collector := &TestReceiptCollector{}
	for i := range TestReceiptCapacity + 2 {
		collector.Emit(RedactionReceipt{ReceiptID: strconv.Itoa(i)})
	}
	got := collector.Receipts()
	if len(got) != TestReceiptCapacity {
		t.Fatalf("retained %d receipts, want %d", len(got), TestReceiptCapacity)
	}
	if got[0].ReceiptID != "2" {
		t.Errorf("oldest retained receipt: got %q, want %q", got[0].ReceiptID, "2")
	}
	if got[len(got)-1].ReceiptID != strconv.Itoa(TestReceiptCapacity+1) {
		t.Errorf("newest retained receipt: got %q", got[len(got)-1].ReceiptID)
	}
	collector.Reset()
	if n := len(collector.Receipts()); n != 0 {
		t.Errorf("Reset left %d receipts", n)
	}
}

// TestReceiptTimestampIsFixedWidthMillis pins the wire spelling. RFC3339Nano
// trims trailing zeros, so the same instant would format to different widths
// depending on its fractional part.
func TestReceiptTimestampIsFixedWidthMillis(t *testing.T) {
	at := time.Date(2026, 8, 4, 12, 34, 56, 789000000, time.UTC)
	if got := _receiptTimestamp(at); got != "2026-08-04T12:34:56.789Z" {
		t.Errorf("got %q", got)
	}
	if got := _receiptTimestamp(time.Date(2026, 8, 4, 12, 34, 56, 0, time.UTC)); got != "2026-08-04T12:34:56.000Z" {
		t.Errorf("zero fraction: got %q", got)
	}
}
