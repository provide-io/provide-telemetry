// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

// Package telemetry — cryptographic redaction receipts.
//
// This file owns two cross-language governance contracts:
//
//   - Canonicalization — the hashed form of a redacted value is its RFC 8785
//     (JCS) serialization, not its %v rendering. Hashing the display form
//     collides across types: the string "1" and the number 1 produce the same
//     digest, so a receipt cannot distinguish them.
//   - Signing — receipt_id|timestamp|field_path|action|original_hash under
//     HMAC-SHA256, lowercase hex.
//
// Both are pinned by spec/receipt_fixtures.yaml.
package telemetry

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"slices"
	"strings"
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

// ReceiptSink is the destination for governance receipts.
//
// Emit reports whether the receipt was accepted. Returning false and panicking
// are equivalent: both increment HealthSnapshot.ReceiptFailures. An
// implementation must not log — see emitReceipt.
type ReceiptSink interface {
	Emit(RedactionReceipt) bool
}

// ErrMissingReceiptSink is returned when receipts are enabled outside test mode
// without a delivery sink. The previous behavior computed a full signed receipt
// for every redaction and then dropped it, so a service could believe it had an
// audit trail and have none.
//
// The message is one literal rather than two joined with `+`. A package-level
// initializer runs before any test does, so Go's coverage tool places it in no
// block and gremlins reports every mutant of that `+` as uncovered — a mutant
// that cannot be covered is a permanent gate failure, and there is nothing to
// test about string concatenation here anyway.
var ErrMissingReceiptSink = errors.New("telemetry: receipts are enabled but no ReceiptSink is configured; generated receipts would be signed and then discarded")

// TestReceiptCapacity bounds TestReceiptCollector.
const TestReceiptCapacity = 1024

// TestReceiptCollector is an in-memory sink for tests, retaining the most
// recent TestReceiptCapacity receipts.
//
// Only the test collector is capped. A production sink is the caller's own
// durable destination, and silently discarding audit records to stay under a
// memory budget is not a decision this library gets to make on their behalf.
type TestReceiptCollector struct {
	mu       sync.Mutex
	receipts []RedactionReceipt
}

// Emit records a receipt, evicting the oldest once the cap is reached.
func (c *TestReceiptCollector) Emit(receipt RedactionReceipt) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	if len(c.receipts) == TestReceiptCapacity {
		copy(c.receipts, c.receipts[1:])
		c.receipts = c.receipts[:TestReceiptCapacity-1]
	}
	c.receipts = append(c.receipts, receipt)
	return true
}

// Receipts returns a copy of the collected receipts, oldest first.
func (c *TestReceiptCollector) Receipts() []RedactionReceipt {
	c.mu.Lock()
	defer c.mu.Unlock()
	return slices.Clone(c.receipts)
}

// Reset discards everything collected so far.
func (c *TestReceiptCollector) Reset() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.receipts = nil
}

// ReceiptOptions configures receipt generation.
type ReceiptOptions struct {
	Enabled bool
	// SigningKey may be empty to emit unsigned receipts.
	SigningKey string
	// ServiceName identifies the emitting service in each receipt.
	ServiceName string
	// Sink receives every generated receipt. Required outside test mode.
	Sink ReceiptSink
}

var (
	_receiptsMu       sync.RWMutex
	_receiptsKey      string
	_receiptsService  string
	_receiptsTestMode bool
	_receiptsSink     ReceiptSink
	_receiptsTestSink TestReceiptCollector
)

// EnableReceipts registers (or deregisters) the redaction receipt hook on the
// PII engine. It returns ErrMissingReceiptSink, leaving the previous state
// untouched, when receipts are enabled in production without a sink.
func EnableReceipts(opts ReceiptOptions) error {
	_receiptsMu.Lock()
	if opts.Enabled && !_receiptsTestMode && opts.Sink == nil {
		_receiptsMu.Unlock()
		return ErrMissingReceiptSink
	}
	_receiptsKey = opts.SigningKey
	_receiptsService = opts.ServiceName
	_receiptsSink = opts.Sink
	_receiptsMu.Unlock()

	if opts.Enabled {
		SetReceiptHook(_onRedaction)
	} else {
		SetReceiptHook(nil)
	}
	return nil
}

// GetEmittedReceiptsForTests returns a copy of receipts collected in test mode.
func GetEmittedReceiptsForTests() []RedactionReceipt {
	return _receiptsTestSink.Receipts()
}

// ResetReceiptsForTests clears all receipt state and enables test-mode collection.
func ResetReceiptsForTests() {
	_receiptsMu.Lock()
	_receiptsKey = ""
	_receiptsService = ""
	_receiptsSink = nil
	_receiptsTestMode = true
	_receiptsMu.Unlock()
	_receiptsTestSink.Reset()
	SetReceiptHook(nil)
}

// receiptFields are the parts of a receipt a caller pins rather than derives.
type receiptFields struct {
	ReceiptID   string
	Timestamp   string
	ServiceName string
	FieldPath   string
	Action      string
}

// receiptPayload is the byte order every SDK signs.
func receiptPayload(receipt RedactionReceipt) string {
	return strings.Join([]string{
		receipt.ReceiptID,
		receipt.Timestamp,
		receipt.FieldPath,
		receipt.Action,
		receipt.OriginalHash,
	}, "|")
}

// signReceipt hashes original in canonical form and signs the resulting
// payload. An empty key yields an unsigned receipt rather than an error:
// unsigned receipts still carry a tamper-evident hash of what was redacted.
func signReceipt(original any, fields receiptFields, key string) RedactionReceipt {
	sum := sha256.Sum256([]byte(CanonicalJSON(original)))
	receipt := RedactionReceipt{
		ReceiptID:    fields.ReceiptID,
		Timestamp:    fields.Timestamp,
		ServiceName:  fields.ServiceName,
		FieldPath:    fields.FieldPath,
		Action:       fields.Action,
		OriginalHash: hex.EncodeToString(sum[:]),
	}
	if key != "" {
		mac := hmac.New(sha256.New, []byte(key))
		mac.Write([]byte(receiptPayload(receipt))) //nolint:errcheck // hash.Hash.Write never returns an error
		receipt.HMAC = hex.EncodeToString(mac.Sum(nil))
	}
	return receipt
}

// emitReceipt hands a receipt to its sink, counting refusals.
//
// This path must never log. The logger is what produces redactions, redactions
// are what produce receipts, and a sink that fails on every receipt would then
// drive an unbounded log→receipt→log cycle. A refusal is recorded only as a
// counter, which GetHealthSnapshot().ReceiptFailures exposes.
func emitReceipt(receipt RedactionReceipt, sink ReceiptSink) {
	if !callReceiptSink(sink, receipt) {
		_incReceiptFailures()
	}
}

// callReceiptSink invokes a sink behind a panic boundary. A sink that panics
// must not take down the log call that produced the redaction, and it is
// counted exactly as a refusal is: the receipt did not arrive either way.
func callReceiptSink(sink ReceiptSink, receipt RedactionReceipt) (accepted bool) {
	defer func() {
		if recover() != nil {
			accepted = false
		}
	}()
	return sink.Emit(receipt)
}

// _receiptTimestamp renders millisecond-precision UTC ISO-8601, the spelling
// every SDK's receipts use. time.RFC3339Nano is not interchangeable with it:
// it trims trailing zeros, so the same instant formats to a different width
// depending on its fractional part.
func _receiptTimestamp(at time.Time) string {
	return at.UTC().Format("2006-01-02T15:04:05.000Z")
}

// _onRedaction is the hook registered with the PII engine.
func _onRedaction(fieldPath string, action string, originalValue any) {
	_receiptsMu.RLock()
	key := _receiptsKey
	sink := _receiptsSink
	fields := receiptFields{
		ReceiptID:   uuid.New().String(),
		Timestamp:   _receiptTimestamp(time.Now()),
		ServiceName: _receiptsService,
		FieldPath:   fieldPath,
		Action:      action,
	}
	if _receiptsTestMode {
		// The built-in collector stands in for a configured sink so the suite
		// never has to exercise the un-sinked path EnableReceipts now rejects.
		sink = &_receiptsTestSink
	}
	_receiptsMu.RUnlock()

	emitReceipt(signReceipt(originalValue, fields, key), sink)
}
