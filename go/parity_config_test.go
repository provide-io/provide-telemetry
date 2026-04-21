// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// parity_config_test.go validates Go behavioral parity for OTLP config header
// parsing and error fingerprint generation against spec/behavioral_fixtures.yaml:
// plus-sign literals preserved in header key/value, percent-encoded spaces
// decoded, fingerprint length is 12 hex chars, and fingerprint with parts.

package telemetry

import (
	"testing"
)

// ── Config Headers Plus Literal ─────────────────────────────────────────────

func TestParity_ConfigHeaders_PlusPreserved(t *testing.T) {
	result := parseOTLPHeaders("a+b=c+d")
	if val, ok := result["a+b"]; !ok || val != "c+d" {
		t.Fatalf("expected {a+b: c+d}, got %v", result)
	}
}

func TestParity_ConfigHeaders_PercentSpace(t *testing.T) {
	result := parseOTLPHeaders("a%20b=c%20d")
	if val, ok := result["a b"]; !ok || val != "c d" {
		t.Fatalf("expected {a b: c d}, got %v", result)
	}
}

// ── Error Fingerprint ─────────────────────────────────────────────────────────

func TestParity_ErrorFingerprint_NoFrames(t *testing.T) {
	fp := ComputeErrorFingerprint("ValueError", nil)
	if len(fp) != 12 {
		t.Fatalf("expected 12-char fingerprint, got %d chars: %q", len(fp), fp)
	}
	expected := "a50aba76697e"
	if fp != expected {
		t.Errorf("fingerprint mismatch: got %q, want %q", fp, expected)
	}
}

func TestParity_ErrorFingerprint_WithParts(t *testing.T) {
	fp := ComputeErrorFingerprintFromParts("TypeError", []string{"module:main", "handler:process"})
	if len(fp) != 12 {
		t.Fatalf("expected 12-char fingerprint, got %d chars: %q", len(fp), fp)
	}
}
