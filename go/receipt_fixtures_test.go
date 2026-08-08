// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

package telemetry

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"testing"

	"gopkg.in/yaml.v3"
)

// The canonical governance vectors in spec/receipt_fixtures.yaml were produced
// by independent implementations — rfc8785 for the canonical JSON, Python's
// hmac for the signatures — so reproducing them byte for byte is evidence of
// cross-language agreement rather than of agreeing with ourselves.

type _receiptFixture struct {
	ID            string `yaml:"id"`
	Key           string `yaml:"key"`
	Input         any    `yaml:"input"`
	Normalized    any    `yaml:"normalized"`
	CanonicalJSON string `yaml:"canonical_json"`
	ReceiptID     string `yaml:"receipt_id"`
	Timestamp     string `yaml:"timestamp"`
	FieldPath     string `yaml:"field_path"`
	Action        string `yaml:"action"`
	OriginalHash  string `yaml:"original_hash"`
	Payload       string `yaml:"payload"`
	Signature     string `yaml:"signature"`
}

type _receiptFixtureFile struct {
	Version int               `yaml:"version"`
	Cases   []_receiptFixture `yaml:"cases"`
}

func _loadReceiptFixtures(t *testing.T) []_receiptFixture {
	t.Helper()
	path := filepath.Join("..", "spec", "receipt_fixtures.yaml")
	raw, err := os.ReadFile(path) //nolint:gosec // fixed in-repo fixture path
	if err != nil {
		t.Fatalf("reading %s: %v", path, err)
	}
	var file _receiptFixtureFile
	if err := yaml.Unmarshal(raw, &file); err != nil {
		t.Fatalf("parsing %s: %v", path, err)
	}
	if len(file.Cases) == 0 {
		t.Fatalf("%s declared no cases", path)
	}
	return file.Cases
}

// TestReceiptFixturesCanonicalJSON pins the RFC 8785 serialization, from both
// the value as captured and the value after normalization. The two forms differ
// only where JSON cannot encode the input — NaN and ±Infinity — and both must
// land on the same bytes, which is what makes the digest independent of how a
// non-finite number reached the hook.
func TestReceiptFixturesCanonicalJSON(t *testing.T) {
	for _, tc := range _loadReceiptFixtures(t) {
		t.Run(tc.ID, func(t *testing.T) {
			if got := CanonicalJSON(tc.Input); got != tc.CanonicalJSON {
				t.Errorf("canonical JSON of input:\n got: %s\nwant: %s", got, tc.CanonicalJSON)
			}
			if got := CanonicalJSON(tc.Normalized); got != tc.CanonicalJSON {
				t.Errorf("canonical JSON of normalized:\n got: %s\nwant: %s", got, tc.CanonicalJSON)
			}
		})
	}
}

// TestReceiptFixturesSignedReceipts pins the whole receipt: the hash over the
// canonical bytes, the payload field order, and the HMAC over that payload.
func TestReceiptFixturesSignedReceipts(t *testing.T) {
	for _, tc := range _loadReceiptFixtures(t) {
		t.Run(tc.ID, func(t *testing.T) {
			receipt := signReceipt(tc.Input, receiptFields{
				ReceiptID:   tc.ReceiptID,
				Timestamp:   tc.Timestamp,
				ServiceName: "fixture-svc",
				FieldPath:   tc.FieldPath,
				Action:      tc.Action,
			}, tc.Key)

			if receipt.OriginalHash != tc.OriginalHash {
				t.Errorf("original_hash:\n got: %s\nwant: %s", receipt.OriginalHash, tc.OriginalHash)
			}
			if got := receiptPayload(receipt); got != tc.Payload {
				t.Errorf("payload:\n got: %s\nwant: %s", got, tc.Payload)
			}
			if receipt.HMAC != tc.Signature {
				t.Errorf("signature:\n got: %s\nwant: %s", receipt.HMAC, tc.Signature)
			}
		})
	}
}

// TestReceiptFixturesHashCoversCanonicalBytes re-derives each digest from the
// fixture's own canonical_json string, so a bug that happened to affect both
// our serializer and our hasher the same way cannot hide.
func TestReceiptFixturesHashCoversCanonicalBytes(t *testing.T) {
	for _, tc := range _loadReceiptFixtures(t) {
		t.Run(tc.ID, func(t *testing.T) {
			sum := sha256.Sum256([]byte(tc.CanonicalJSON))
			if got := hex.EncodeToString(sum[:]); got != tc.OriginalHash {
				t.Errorf("fixture is self-inconsistent: %s vs %s", got, tc.OriginalHash)
			}
			mac := hmac.New(sha256.New, []byte(tc.Key))
			mac.Write([]byte(tc.Payload)) //nolint:errcheck // hash.Hash.Write never errors
			if got := hex.EncodeToString(mac.Sum(nil)); got != tc.Signature {
				t.Errorf("fixture signature is self-inconsistent: %s vs %s", got, tc.Signature)
			}
		})
	}
}
