// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// parity_pii_test.go validates Go behavioral parity for PII handling against
// spec/behavioral_fixtures.yaml: hash format, hash determinism, hash of
// non-string values, truncate (longer/at/shorter than limit, non-string),
// redact (case-insensitive sensitive keys), drop mode, and secret detection
// (AWS keys, JWTs, GitHub tokens, normal strings).

package telemetry

import (
	"crypto/sha256"
	"fmt"
	"regexp"
	"testing"
)

// ── PII Hash ─────────────────────────────────────────────────────────────────

func TestParity_PIIHash_Format(t *testing.T) {
	sum := sha256.Sum256([]byte("user-42"))
	hash := fmt.Sprintf("%x", sum)[:12]
	if len(hash) != 12 {
		t.Fatalf("hash length: want 12, got %d", len(hash))
	}
	if matched, _ := regexp.MatchString(`^[0-9a-f]{12}$`, hash); !matched {
		t.Errorf("hash not lowercase hex: %q", hash)
	}
}

func TestParity_PIIHash_Deterministic(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{{Path: []string{"uid"}, Mode: PIIModeHash}})
	r := SanitizePayload(map[string]any{"uid": "same-input"}, true, 32)
	if r["uid"] != "f52c2013103b" {
		t.Errorf("hash(same-input): want f52c2013103b, got %v", r["uid"])
	}
}

func TestParity_PIIHash_Integer(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{{Path: []string{"n"}, Mode: PIIModeHash}})
	r := SanitizePayload(map[string]any{"n": 42}, true, 32)
	if r["n"] != "73475cb40a56" { // pragma: allowlist secret
		t.Errorf("hash(42): want 73475cb40a56, got %v", r["n"])
	}
}

// ── PII Truncate ─────────────────────────────────────────────────────────────

func TestParity_PIITruncate_LongerThanLimit(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{{Path: []string{"note"}, Mode: PIIModeTruncate, TruncateTo: 5}})
	r := SanitizePayload(map[string]any{"note": "hello world"}, true, 32)
	if r["note"] != "hello..." {
		t.Errorf("truncate(hello world, 5): want %q, got %v", "hello...", r["note"])
	}
}

func TestParity_PIITruncate_AtLimit_Unchanged(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{{Path: []string{"note"}, Mode: PIIModeTruncate, TruncateTo: 5}})
	r := SanitizePayload(map[string]any{"note": "hello"}, true, 32)
	if r["note"] != "hello" {
		t.Errorf("truncate(hello, 5): at limit should be unchanged, got %v", r["note"])
	}
}

func TestParity_PIITruncate_ShorterThanLimit_Unchanged(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{{Path: []string{"note"}, Mode: PIIModeTruncate, TruncateTo: 5}})
	r := SanitizePayload(map[string]any{"note": "hi"}, true, 32)
	if r["note"] != "hi" {
		t.Errorf("truncate(hi, 5): should be unchanged, got %v", r["note"])
	}
}

// ── PII Redact ───────────────────────────────────────────────────────────────

func TestParity_PIIRedact_SensitiveKey(t *testing.T) {
	resetPII(t)
	r := SanitizePayload(map[string]any{"password": "s3cret"}, true, 32) // pragma: allowlist secret
	if r["password"] != "***" {                                           // pragma: allowlist secret
		t.Errorf("redact(password): want ***, got %v", r["password"])
	}
}

func TestParity_PIIRedact_CaseInsensitive(t *testing.T) {
	resetPII(t)
	r := SanitizePayload(map[string]any{"API_KEY": "abc123"}, true, 32)
	if r["API_KEY"] != "***" {
		t.Errorf("redact(API_KEY): want ***, got %v", r["API_KEY"])
	}
}

// ── PII Truncate — non-string conversion ─────────────────────────────────────

func TestParity_PIITruncate_NonString(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{{Path: []string{"count"}, Mode: PIIModeTruncate, TruncateTo: 3}})
	result := SanitizePayload(map[string]any{"count": 12345}, true, 0)
	if result["count"] != "123..." {
		t.Errorf("expected truncated non-string '123...', got %v", result["count"])
	}
}

// ── PII Drop — removes key ────────────────────────────────────────────────────

func TestParity_PIIDrop_RemovesKey(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{{Path: []string{"secret_data"}, Mode: PIIModeDrop}})
	result := SanitizePayload(map[string]any{"secret_data": "top-secret", "keep": "visible"}, true, 0) // pragma: allowlist secret
	if _, exists := result["secret_data"]; exists {
		t.Error("expected 'secret_data' to be dropped entirely")
	}
	if result["keep"] != "visible" {
		t.Errorf("expected 'keep' unchanged, got %v", result["keep"])
	}
}

// ── Secret Detection ──────────────────────────────────────────────────────────

func TestParity_SecretDetection_AWSKey(t *testing.T) {
	payload := map[string]any{"data": "AKIAIOSFODNN7EXAMPLE"}
	result := SanitizePayload(payload, true, 0)
	if result["data"] != _piiRedacted {
		t.Errorf("expected AWS key redacted, got %v", result["data"])
	}
}

func TestParity_SecretDetection_JWT(t *testing.T) {
	payload := map[string]any{"data": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"}
	result := SanitizePayload(payload, true, 0)
	if result["data"] != _piiRedacted {
		t.Errorf("expected JWT redacted, got %v", result["data"])
	}
}

func TestParity_SecretDetection_GitHubToken(t *testing.T) {
	payload := map[string]any{"data": "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklm"}
	result := SanitizePayload(payload, true, 0)
	if result["data"] != _piiRedacted {
		t.Errorf("expected GitHub token redacted, got %v", result["data"])
	}
}

func TestParity_SecretDetection_ShortString_NotRedacted(t *testing.T) {
	payload := map[string]any{"data": "not-a-secret"}
	result := SanitizePayload(payload, true, 0)
	if result["data"] != "not-a-secret" {
		t.Errorf("expected short string unchanged, got %v", result["data"])
	}
}

func TestParity_SecretDetection_LongNormalString_NotRedacted(t *testing.T) {
	payload := map[string]any{"data": "hello world this is normal text"}
	result := SanitizePayload(payload, true, 0)
	if result["data"] != "hello world this is normal text" {
		t.Errorf("expected normal string unchanged, got %v", result["data"])
	}
}

// ── Default Sensitive Keys ────────────────────────────────────────────────────

func TestParity_DefaultSensitiveKeys_Cookie(t *testing.T) {
	resetPII(t)
	result := SanitizePayload(map[string]any{"cookie": "session=abc123"}, true, 32)
	if result["cookie"] != _piiRedacted {
		t.Errorf("expected 'cookie' auto-redacted, got %v", result["cookie"])
	}
}

func TestParity_DefaultSensitiveKeys_CVV(t *testing.T) {
	resetPII(t)
	result := SanitizePayload(map[string]any{"cvv": "123"}, true, 32)
	if result["cvv"] != _piiRedacted {
		t.Errorf("expected 'cvv' auto-redacted, got %v", result["cvv"])
	}
}

func TestParity_DefaultSensitiveKeys_PIN(t *testing.T) {
	resetPII(t)
	result := SanitizePayload(map[string]any{"pin": "9876"}, true, 32)
	if result["pin"] != _piiRedacted {
		t.Errorf("expected 'pin' auto-redacted, got %v", result["pin"])
	}
}
