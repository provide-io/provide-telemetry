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

	"github.com/provide-io/provide-telemetry/go/internal/piicore"
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

// Non-string values hash their RFC 8785 canonical JSON, not fmt's %v, so
// every SDK digests the same bytes: true → "true", nil → "null", 1.5 → "1.5",
// objects key-sorted. 42 is unchanged because %v and JCS agree on integers.

func TestParity_PIIHash_Boolean(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{{Path: []string{"flag"}, Mode: PIIModeHash}})
	r := SanitizePayload(map[string]any{"flag": true}, true, 32)
	if r["flag"] != "b5bea41b6c62" { // pragma: allowlist secret
		t.Errorf("hash(true): want b5bea41b6c62, got %v", r["flag"])
	}
}

func TestParity_PIIHash_Null(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{{Path: []string{"nothing"}, Mode: PIIModeHash}})
	r := SanitizePayload(map[string]any{"nothing": nil}, true, 32)
	if r["nothing"] != "74234e98afe7" { // pragma: allowlist secret
		t.Errorf("hash(nil): want 74234e98afe7, got %v", r["nothing"])
	}
}

func TestParity_PIIHash_Float(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{{Path: []string{"ratio"}, Mode: PIIModeHash}})
	r := SanitizePayload(map[string]any{"ratio": 1.5}, true, 32)
	if r["ratio"] != "9f29a130438b" { // pragma: allowlist secret
		t.Errorf("hash(1.5): want 9f29a130438b, got %v", r["ratio"])
	}
}

func TestParity_PIIHash_Object(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{{Path: []string{"obj"}, Mode: PIIModeHash}})
	r := SanitizePayload(map[string]any{"obj": map[string]any{"b": 1, "a": "x"}}, true, 32)
	if r["obj"] != "cdab067e9f3b" { // pragma: allowlist secret
		t.Errorf(`hash({"b":1,"a":"x"}): want cdab067e9f3b, got %v`, r["obj"])
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
	if r["password"] != "***" {                                          // pragma: allowlist secret
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

// A rule registered without a limit truncates to 8, the default every SDK
// shares; Go's zero-value TruncateTo is normalised on registration.
func TestParity_PIITruncate_UnsetLimitDefaultsTo8(t *testing.T) {
	resetPII(t)
	RegisterPIIRule(PIIRule{Path: []string{"note"}, Mode: PIIModeTruncate})
	r := SanitizePayload(map[string]any{"note": "abcdefghij"}, true, 32)
	if r["note"] != "abcdefgh..." {
		t.Errorf("truncate(abcdefghij, unset): want %q, got %v", "abcdefgh...", r["note"])
	}
}

// Registration normalises 0 to the default, so the zero-limit contract — the
// output is exactly the suffix — is exercised against the engine directly.
func TestParity_PIITruncate_ZeroLimit_SuffixOnly(t *testing.T) {
	got, drop := piicore.ApplyMode("hello", PIIModeTruncate, 0)
	if drop || got != "..." {
		t.Errorf("truncate(hello, 0): want %q, got %v (drop=%v)", "...", got, drop)
	}
}

// A negative limit is clamped to 0 — never an error, never the whole value,
// and never a panic on a negative slice bound.
func TestParity_PIITruncate_NegativeLimit_ClampsToZero(t *testing.T) {
	resetPII(t)
	RegisterPIIRule(PIIRule{Path: []string{"note"}, Mode: PIIModeTruncate, TruncateTo: -3})
	r := SanitizePayload(map[string]any{"note": "hello"}, true, 32)
	if r["note"] != "..." {
		t.Errorf("truncate(hello, -3): want %q, got %v", "...", r["note"])
	}
}

// The limit counts Unicode scalar values: five astral emoji cut at 3 keep
// three whole emoji, where a UTF-16 slice would split the second one.
func TestParity_PIITruncate_CountsCodePoints(t *testing.T) {
	resetPII(t)
	RegisterPIIRule(PIIRule{Path: []string{"note"}, Mode: PIIModeTruncate, TruncateTo: 3})
	r := SanitizePayload(map[string]any{"note": "😀😀😀😀😀"}, true, 32)
	if r["note"] != "😀😀😀..." {
		t.Errorf("truncate(5 emoji, 3): want %q, got %v", "😀😀😀...", r["note"])
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

func TestParity_DefaultSensitiveKeys_ExactMatchOnly(t *testing.T) {
	resetPII(t)
	payload := map[string]any{
		"author_id":      "safe-author",
		"spinning_wheel": "safe-spin",
		"glassness":      "safe-word",
	}
	result := SanitizePayload(payload, true, 32)
	if result["author_id"] != payload["author_id"] {
		t.Errorf("expected author_id unchanged, got %v", result["author_id"])
	}
	if result["spinning_wheel"] != payload["spinning_wheel"] {
		t.Errorf("expected spinning_wheel unchanged, got %v", result["spinning_wheel"])
	}
	if result["glassness"] != payload["glassness"] {
		t.Errorf("expected glassness unchanged, got %v", result["glassness"])
	}
}

// ── PII Default Depth ─────────────────────────────────────────────────────────

func TestParity_PIIDepth_DefaultIs8(t *testing.T) {
	resetPII(t)
	// Build 9-level deep nested map with "password" at each level
	payload := map[string]any{"password": "level8_should_survive"}
	for i := 7; i >= 0; i-- {
		payload = map[string]any{
			"password": fmt.Sprintf("level%d", i),
			"nested":   payload,
		}
	}
	result := SanitizePayload(payload, true, 0) // 0 = use default
	// Depth 0 should be redacted
	if result["password"] == fmt.Sprintf("level%d", 0) {
		t.Error("depth 0: expected redacted")
	}
	// Navigate to depth 8
	node := result
	for i := 0; i < 8; i++ {
		nested, ok := node["nested"].(map[string]any)
		if !ok {
			t.Fatalf("depth %d: expected nested map", i+1)
		}
		node = nested
	}
	// Depth 8 should survive (beyond default max_depth=8)
	if node["password"] == _piiRedacted { // pragma: allowlist secret
		t.Error("depth 8: should NOT be redacted with default max_depth=8")
	}
}

// ── Span-Scoped Redaction ────────────────────────────────────────────────────

// TestParity_SecretSpanRedaction mirrors spec/behavioral_fixtures.yaml
// secret_span_redaction. The cases that matter are the ones a single-span
// implementation gets wrong: a value holding two secrets, and a secret sitting
// behind a filesystem path that the base64 rule matches first.
func TestParity_SecretSpanRedaction(t *testing.T) {
	cases := []struct{ in, want, note string }{
		{
			in:   "token AKIAIOSFODNN7EXAMPLE leaked",
			want: "token *** leaked",
			note: "surrounding words survive",
		},
		{
			in:   "first AKIAIOSFODNN7EXAMPLE second AKIAIOSFODNN7EXAMPLB",
			want: "first *** second ***",
			note: "every secret goes, not only the first",
		},
		{
			in:   "/home/deploy/apps/production/current/lib/service c2VjcmV0a2V5MTIzNDU2Nzg5MGFiY2RlZmdoaWprbG1ub3A",
			want: "/home/deploy/apps/production/current/lib/service ***",
			note: "a suppressed path does not shadow the secret behind it",
		},
		{
			in:   "make -C /home/deploy/apps/production/current/native/capture install",
			want: "make -C /home/deploy/apps/production/current/native/capture install",
			note: "no secret, no change",
		},
	}
	for _, c := range cases {
		result := SanitizePayload(map[string]any{"data": c.in}, true, 32)
		if got := result["data"]; got != c.want {
			t.Errorf("%s\n  in:   %s\n  want: %s\n  got:  %v", c.note, c.in, c.want, got)
		}
	}
}
