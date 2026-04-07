// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

// Package telemetry — cryptographic redaction receipts (strippable governance module).
// If this file is deleted, the PII engine runs unchanged (hook stays nil).
package telemetry

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/google/uuid"
)

// RedactionReceipt is an immutable audit record for a single PII redaction event.
type RedactionReceipt struct {
	ReceiptID    string
	Timestamp    string
	ServiceName  string
	FieldPath    string
	Action       string
	OriginalHash string
	HMAC         string
}

var (
	_receiptsMu       sync.RWMutex
	_receiptsKey      string
	_receiptsService  string
	_receiptsTestMode bool
	_receiptsStore    []RedactionReceipt
)

// EnableReceipts registers (or deregisters) the redaction receipt hook on the PII engine.
// signingKey may be empty to disable HMAC signing.
// serviceName identifies the service in each receipt.
func EnableReceipts(enabled bool, signingKey string, serviceName string) {
	_receiptsMu.Lock()
	_receiptsKey = signingKey
	_receiptsService = serviceName
	_receiptsMu.Unlock()

	if enabled {
		SetReceiptHook(_onRedaction)
	} else {
		SetReceiptHook(nil)
	}
}

// GetEmittedReceiptsForTests returns a copy of receipts collected in test mode.
func GetEmittedReceiptsForTests() []RedactionReceipt {
	_receiptsMu.RLock()
	defer _receiptsMu.RUnlock()
	out := make([]RedactionReceipt, len(_receiptsStore))
	copy(out, _receiptsStore)
	return out
}

// ResetReceiptsForTests clears all receipt state and enables test-mode collection.
func ResetReceiptsForTests() {
	_receiptsMu.Lock()
	_receiptsKey = ""
	_receiptsStore = nil
	_receiptsTestMode = true
	_receiptsMu.Unlock()
	SetReceiptHook(nil)
}

// _onRedaction is the hook registered with the PII engine.
func _onRedaction(fieldPath string, action string, originalValue any) {
	receiptID := uuid.New().String()
	timestamp := time.Now().UTC().Format(time.RFC3339Nano)
	sum := sha256.Sum256([]byte(fmt.Sprintf("%v", originalValue)))
	originalHash := hex.EncodeToString(sum[:])

	_receiptsMu.RLock()
	key := _receiptsKey
	svc := _receiptsService
	inTest := _receiptsTestMode
	_receiptsMu.RUnlock()

	hmacValue := ""
	if key != "" {
		payload := fmt.Sprintf("%s|%s|%s|%s|%s", receiptID, timestamp, fieldPath, action, originalHash)
		mac := hmac.New(sha256.New, []byte(key))
		mac.Write([]byte(payload)) //nolint:errcheck
		hmacValue = hex.EncodeToString(mac.Sum(nil))
	}

	receipt := RedactionReceipt{
		ReceiptID:    receiptID,
		Timestamp:    timestamp,
		ServiceName:  svc,
		FieldPath:    fieldPath,
		Action:       action,
		OriginalHash: originalHash,
		HMAC:         hmacValue,
	}

	if inTest {
		_receiptsMu.Lock()
		_receiptsStore = append(_receiptsStore, receipt)
		_receiptsMu.Unlock()
	} else {
		slog.Debug("provide.pii.redaction_receipt",
			"receipt_id", receipt.ReceiptID,
			"field_path", receipt.FieldPath,
		)
	}
}
