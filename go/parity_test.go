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

// ── Backpressure Parity ───────────────────────────────────────────────────────

func TestParity_Backpressure_DefaultUnlimited(t *testing.T) {
	_resetQueuePolicy()
	t.Cleanup(_resetQueuePolicy)

	policy := GetQueuePolicy()
	if policy.LogsMaxSize != 0 {
		t.Errorf("expected default LogsMaxSize=0 (unlimited), got %d", policy.LogsMaxSize)
	}
	if policy.TracesMaxSize != 0 {
		t.Errorf("expected default TracesMaxSize=0 (unlimited), got %d", policy.TracesMaxSize)
	}
	if policy.MetricsMaxSize != 0 {
		t.Errorf("expected default MetricsMaxSize=0 (unlimited), got %d", policy.MetricsMaxSize)
	}
}

func TestParity_Backpressure_UnlimitedAlwaysAcquires(t *testing.T) {
	_resetQueuePolicy()
	t.Cleanup(_resetQueuePolicy)

	for i := 0; i < 5000; i++ {
		if !TryAcquire(signalLogs) {
			t.Fatalf("TryAcquire failed at iteration %d with unlimited queue", i)
		}
	}
}

// ── Error Fingerprint ─────────────────────────────────────────────────────────

func TestParity_ErrorFingerprint_NoFrames(t *testing.T) {
	fp := _computeErrorFingerprint("ValueError", nil)
	if len(fp) != 12 {
		t.Fatalf("expected 12-char fingerprint, got %d chars: %q", len(fp), fp)
	}
	expected := "a50aba76697e"
	if fp != expected {
		t.Errorf("fingerprint mismatch: got %q, want %q", fp, expected)
	}
}

func TestParity_ErrorFingerprint_WithParts(t *testing.T) {
	fp := _computeErrorFingerprintFromParts("TypeError", []string{"module:main", "handler:process"})
	if len(fp) != 12 {
		t.Fatalf("expected 12-char fingerprint, got %d chars: %q", len(fp), fp)
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

// ── Propagation Guards — baggage limits ──────────────────────────────────────

func TestParity_Propagation_BaggageAtLimit_Accepted(t *testing.T) {
	headers := http.Header{}
	headers.Set("Baggage", strings.Repeat("x", 8192))
	pc := ExtractW3CContext(headers)
	if pc.Baggage == "" {
		t.Error("expected baggage at limit (8192) to be accepted")
	}
}

func TestParity_Propagation_BaggageOverLimit_Discarded(t *testing.T) {
	headers := http.Header{}
	headers.Set("Baggage", strings.Repeat("x", 8193))
	pc := ExtractW3CContext(headers)
	if pc.Baggage != "" {
		t.Error("expected baggage over limit (8193) to be discarded")
	}
}

// ── SLO Classify — edge cases ─────────────────────────────────────────────────

func TestParity_ClassifyError_200_Unknown(t *testing.T) {
	result := ClassifyError("", 200)
	if result["error.category"] != "unknown" {
		t.Errorf("expected unknown for 200, got %s", result["error.category"])
	}
}

func TestParity_ClassifyError_301_Unknown(t *testing.T) {
	result := ClassifyError("", 301)
	if result["error.category"] != "unknown" {
		t.Errorf("expected unknown for 301, got %s", result["error.category"])
	}
}

func TestParity_ClassifyError_TimeoutByExcName(t *testing.T) {
	result := ClassifyError("ConnectionTimeoutError", 503)
	if result["error.category"] != "timeout" {
		t.Errorf("expected timeout by exc name, got %s", result["error.category"])
	}
}

func TestParity_ClassifyError_599_ServerError(t *testing.T) {
	result := ClassifyError("ServerError", 599)
	if result["error.category"] != "server_error" {
		t.Errorf("expected server_error for 599, got %s", result["error.category"])
	}
}

// ── Backpressure Unlimited ──────────────────────────────────────────────────

func TestParity_Backpressure_ZeroIsUnlimited(t *testing.T) {
	_resetQueuePolicy()
	t.Cleanup(_resetQueuePolicy)
	t.Cleanup(_resetHealth)

	SetQueuePolicy(QueuePolicy{LogsMaxSize: 0, TracesMaxSize: 0, MetricsMaxSize: 0})
	// 100 concurrent acquires must all succeed without release.
	for i := 0; i < 100; i++ {
		if !TryAcquire(signalLogs) {
			t.Fatalf("acquire %d failed with unlimited (0) queue", i)
		}
	}
}

func TestParity_Backpressure_BoundedRejects(t *testing.T) {
	_resetQueuePolicy()
	_resetHealth()
	t.Cleanup(_resetQueuePolicy)
	t.Cleanup(_resetHealth)

	SetQueuePolicy(QueuePolicy{LogsMaxSize: 1, TracesMaxSize: 1, MetricsMaxSize: 1})
	if !TryAcquire(signalLogs) {
		t.Fatal("first acquire must succeed")
	}
	if TryAcquire(signalLogs) {
		t.Fatal("second acquire must fail with queue size 1")
	}
}

// ── Cardinality Clamping ────────────────────────────────────────────────────

func TestParity_Cardinality_ZeroMaxValuesClamped(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("k", CardinalityLimit{MaxValues: 0, TTLSeconds: 10.0})
	got := GetCardinalityLimit("k")
	if got.MaxValues != 1 {
		t.Fatalf("expected MaxValues clamped to 1, got %d", got.MaxValues)
	}
	if got.TTLSeconds != 10.0 {
		t.Fatalf("expected TTLSeconds 10.0, got %f", got.TTLSeconds)
	}
}

func TestParity_Cardinality_NegativeMaxValuesClamped(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("k", CardinalityLimit{MaxValues: -5, TTLSeconds: 10.0})
	got := GetCardinalityLimit("k")
	if got.MaxValues != 1 {
		t.Fatalf("expected MaxValues clamped to 1, got %d", got.MaxValues)
	}
}

func TestParity_Cardinality_ZeroTTLClamped(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("k", CardinalityLimit{MaxValues: 10, TTLSeconds: 0.0})
	got := GetCardinalityLimit("k")
	if got.TTLSeconds != 1.0 {
		t.Fatalf("expected TTLSeconds clamped to 1.0, got %f", got.TTLSeconds)
	}
}

func TestParity_Cardinality_NegativeTTLClamped(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("k", CardinalityLimit{MaxValues: 10, TTLSeconds: -3.0})
	got := GetCardinalityLimit("k")
	if got.TTLSeconds != 1.0 {
		t.Fatalf("expected TTLSeconds clamped to 1.0, got %f", got.TTLSeconds)
	}
}

func TestParity_Cardinality_ValidValuesUnchanged(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("k", CardinalityLimit{MaxValues: 50, TTLSeconds: 300.0})
	got := GetCardinalityLimit("k")
	if got.MaxValues != 50 {
		t.Fatalf("expected MaxValues 50, got %d", got.MaxValues)
	}
	if got.TTLSeconds != 300.0 {
		t.Fatalf("expected TTLSeconds 300.0, got %f", got.TTLSeconds)
	}
}

// ── Schema Strict Mode ──────────────────────────────────────────────────────

func TestParity_EventName_LenientAcceptsUppercase(t *testing.T) {
	origStrict := _strictSchema
	_strictSchema = false
	t.Cleanup(func() { _strictSchema = origStrict })

	name, err := EventName("A", "B", "C")
	if err != nil {
		t.Fatalf("lenient EventName should accept uppercase, got error: %v", err)
	}
	if name != "A.B.C" {
		t.Fatalf("expected A.B.C, got %s", name)
	}
}

func TestParity_EventName_LenientAcceptsMixedCase(t *testing.T) {
	origStrict := _strictSchema
	_strictSchema = false
	t.Cleanup(func() { _strictSchema = origStrict })

	name, err := EventName("User", "Login", "Ok")
	if err != nil {
		t.Fatalf("lenient EventName should accept mixed case, got error: %v", err)
	}
	if name != "User.Login.Ok" {
		t.Fatalf("expected User.Login.Ok, got %s", name)
	}
}

func TestParity_EventName_StrictRejectsUppercase(t *testing.T) {
	origStrict := _strictSchema
	_strictSchema = true
	t.Cleanup(func() { _strictSchema = origStrict })

	_, err := EventName("User", "login", "ok")
	if err == nil {
		t.Fatal("strict EventName should reject uppercase segment")
	}
}

func TestParity_EventName_StrictAcceptsValid(t *testing.T) {
	origStrict := _strictSchema
	_strictSchema = true
	t.Cleanup(func() { _strictSchema = origStrict })

	name, err := EventName("user", "login", "ok")
	if err != nil {
		t.Fatalf("strict EventName should accept valid segments, got: %v", err)
	}
	if name != "user.login.ok" {
		t.Fatalf("expected user.login.ok, got %s", name)
	}
}
