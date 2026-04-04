// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// parity_test.go validates Go behavioral parity against spec/behavioral_fixtures.yaml.
// Python and TypeScript have equivalent test files validating the same fixtures.

package telemetry

import (
	"crypto/sha256"
	"fmt"
	"net/http"
	"regexp"
	"strings"
	"testing"
)

// ── Sampling ─────────────────────────────────────────────────────────────────

func TestParity_Sampling_RateZero_AlwaysDrops(t *testing.T) {
	_resetSamplingPolicies()
	_resetHealth()
	t.Cleanup(_resetSamplingPolicies)
	t.Cleanup(_resetHealth)

	SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 0.0})
	for i := 0; i < 100; i++ {
		if ShouldSample(signalLogs, "evt") {
			t.Fatal("rate=0.0 must never sample")
		}
	}
}

func TestParity_Sampling_RateOne_AlwaysKeeps(t *testing.T) {
	_resetSamplingPolicies()
	_resetHealth()
	t.Cleanup(_resetSamplingPolicies)
	t.Cleanup(_resetHealth)

	SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 1.0})
	for i := 0; i < 100; i++ {
		if !ShouldSample(signalLogs, "evt") {
			t.Fatal("rate=1.0 must always sample")
		}
	}
}

func TestParity_Sampling_RateHalf_Statistical(t *testing.T) {
	_resetSamplingPolicies()
	_resetHealth()
	t.Cleanup(_resetSamplingPolicies)
	t.Cleanup(_resetHealth)

	SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 0.5})
	count := 0
	const n = 10000
	for i := 0; i < n; i++ {
		if ShouldSample(signalLogs, "evt") {
			count++
		}
	}
	pct := float64(count) / float64(n) * 100
	if pct < 40 || pct > 60 {
		t.Errorf("rate=0.5: expected 40-60%%, got %.1f%%", pct)
	}
}

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

// ── Event DARS ───────────────────────────────────────────────────────────────

func TestParity_Event_DAS(t *testing.T) {
	evt, err := Event("user", "login", "ok")
	if err != nil {
		t.Fatalf("Event(user,login,ok) error: %v", err)
	}
	if evt.Event != "user.login.ok" {
		t.Errorf("event: want user.login.ok, got %q", evt.Event)
	}
	if evt.Domain != "user" || evt.Action != "login" || evt.Status != "ok" {
		t.Errorf("fields: got domain=%q action=%q status=%q", evt.Domain, evt.Action, evt.Status)
	}
	if evt.Resource != "" {
		t.Errorf("resource: want empty for DAS, got %q", evt.Resource)
	}
}

func TestParity_Event_DARS(t *testing.T) {
	evt, err := Event("db", "query", "users", "ok")
	if err != nil {
		t.Fatalf("Event(db,query,users,ok) error: %v", err)
	}
	if evt.Event != "db.query.users.ok" {
		t.Errorf("event: want db.query.users.ok, got %q", evt.Event)
	}
	if evt.Domain != "db" || evt.Action != "query" || evt.Resource != "users" || evt.Status != "ok" {
		t.Errorf("fields: got domain=%q action=%q resource=%q status=%q",
			evt.Domain, evt.Action, evt.Resource, evt.Status)
	}
}

func TestParity_Event_TooFew(t *testing.T) {
	_, err := Event("too", "few")
	if err == nil {
		t.Error("Event(too,few) should error")
	}
}

func TestParity_Event_TooMany(t *testing.T) {
	_, err := Event("a", "b", "c", "d", "e")
	if err == nil {
		t.Error("Event(a,b,c,d,e) should error")
	}
}

// ── Propagation Guards ───────────────────────────────────────────────────────

func TestParity_Propagation_TraceparentAtLimit_Accepted(t *testing.T) {
	headers := http.Header{}
	tp := "00-" + _validTraceID + "-" + _validSpanID + "-01"
	headers.Set("Traceparent", tp)
	pc := ExtractW3CContext(headers)
	if pc.Traceparent == "" {
		t.Error("traceparent within 512 bytes should be accepted")
	}
}

func TestParity_Propagation_TraceparentOverLimit_Handled(t *testing.T) {
	headers := http.Header{}
	long := strings.Repeat("x", 513)
	headers.Set("Traceparent", long)
	pc := ExtractW3CContext(headers)
	if pc.Traceparent != "" {
		t.Errorf("oversized traceparent should be discarded, got %d bytes", len(pc.Traceparent))
	}
}

func TestParity_Propagation_Tracestate32Pairs_Accepted(t *testing.T) {
	headers := http.Header{}
	headers.Set("Traceparent", validTraceparent())
	pairs := make([]string, 32)
	for i := range pairs {
		pairs[i] = "k=v"
	}
	headers.Set("Tracestate", strings.Join(pairs, ","))
	pc := ExtractW3CContext(headers)
	if pc.Tracestate == "" {
		t.Error("32 tracestate pairs should be accepted")
	}
}

func TestParity_Propagation_Tracestate33Pairs_Handled(t *testing.T) {
	headers := http.Header{}
	headers.Set("Traceparent", validTraceparent())
	pairs := make([]string, 33)
	for i := range pairs {
		pairs[i] = "k=v"
	}
	headers.Set("Tracestate", strings.Join(pairs, ","))
	pc := ExtractW3CContext(headers)
	if pc.Tracestate != "" {
		t.Errorf("33 tracestate pairs should be discarded, got %q", pc.Tracestate)
	}
}

// ���─ SLO Classify ─────────────────────────────────────────────────────────────

func TestParity_ClassifyError_400(t *testing.T) {
	m := ClassifyError("BadRequest", 400)
	if m["error.category"] != "client_error" {
		t.Errorf("400 category: want client_error, got %s", m["error.category"])
	}
}

func TestParity_ClassifyError_500(t *testing.T) {
	m := ClassifyError("InternalServerError", 500)
	if m["error.category"] != "server_error" {
		t.Errorf("500 category: want server_error, got %s", m["error.category"])
	}
}

func TestParity_ClassifyError_429(t *testing.T) {
	m := ClassifyError("TooManyRequests", 429)
	if m["error.category"] != "client_error" {
		t.Errorf("429 category: want client_error, got %s", m["error.category"])
	}
	if m["error.severity"] != "critical" {
		t.Errorf("429 severity: want critical, got %s", m["error.severity"])
	}
}

func TestParity_ClassifyError_0(t *testing.T) {
	m := ClassifyError("ConnectionError", 0)
	if m["error.category"] != "timeout" {
		t.Errorf("0 category: want timeout, got %s", m["error.category"])
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
