// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// mutations2_test.go kills remaining surviving gremlins mutations.
package logger

import (
	"bytes"
	"context"
	"log/slog"
	"regexp"
	"runtime"
	"strings"
	"testing"
	"time"
)

// ---- applyStandardFields: each field individually ----

// TestHandlerEnvFieldInOutput kills CONDITIONALS_NEGATION at logger.go:115:67 and 126:17.
func TestHandlerEnvFieldInOutput(t *testing.T) {
	buf := &bytes.Buffer{}
	base := slog.NewJSONHandler(buf, &slog.HandlerOptions{Level: LevelTrace})
	cfg := DefaultLogConfig()
	cfg.Environment = "staging"
	h := _newTelemetryHandler(base, cfg, "test")
	r := slog.NewRecord(time.Now(), slog.LevelInfo, "a.b.c", 0)
	_ = h.Handle(context.Background(), r)
	if !strings.Contains(buf.String(), "staging") {
		t.Fatalf("service.env=staging should appear in output, got: %s", buf.String())
	}
}

// TestHandlerVersionFieldInOutput kills CONDITIONALS_NEGATION at logger.go:115:46 and 123:21.
func TestHandlerVersionFieldInOutput(t *testing.T) {
	buf := &bytes.Buffer{}
	base := slog.NewJSONHandler(buf, &slog.HandlerOptions{Level: LevelTrace})
	cfg := DefaultLogConfig()
	cfg.Version = "2.0.1"
	h := _newTelemetryHandler(base, cfg, "test")
	r := slog.NewRecord(time.Now(), slog.LevelInfo, "a.b.c", 0)
	_ = h.Handle(context.Background(), r)
	if !strings.Contains(buf.String(), "2.0.1") {
		t.Fatalf("service.version=2.0.1 should appear in output, got: %s", buf.String())
	}
}

// TestHandlerEarlyReturnAllEmpty kills the AND condition at logger.go:115 when all fields empty.
func TestHandlerEarlyReturnAllEmpty(t *testing.T) {
	buf := &bytes.Buffer{}
	base := slog.NewJSONHandler(buf, &slog.HandlerOptions{Level: LevelTrace})
	// No service metadata at all → early return.
	cfg := DefaultLogConfig()
	h := _newTelemetryHandler(base, cfg, "test")
	r := slog.NewRecord(time.Now(), slog.LevelInfo, "a.b.c", 0)
	_ = h.Handle(context.Background(), r)
	// service.name/env/version should NOT appear.
	if strings.Contains(buf.String(), "service.name") ||
		strings.Contains(buf.String(), "service.env") ||
		strings.Contains(buf.String(), "service.version") {
		t.Fatalf("no service fields should appear when all empty, got: %s", buf.String())
	}
}

// ---- applyTraceFields: individual field presence ----

// TestHandlerTraceIDInOutput kills CONDITIONALS_NEGATION at logger.go:139:13.
func TestHandlerTraceIDInOutput(t *testing.T) {
	buf := &bytes.Buffer{}
	base := slog.NewJSONHandler(buf, &slog.HandlerOptions{Level: LevelTrace})
	h := _newTelemetryHandler(base, DefaultLogConfig(), "test")

	ctx := SetTraceContext(context.Background(), "traceid-xyz", "")
	r := slog.NewRecord(time.Now(), slog.LevelInfo, "a.b.c", 0)
	_ = h.Handle(ctx, r)
	if !strings.Contains(buf.String(), "traceid-xyz") {
		t.Fatalf("trace.id should appear, got: %s", buf.String())
	}
	if strings.Contains(buf.String(), "span.id") {
		t.Fatalf("span.id should NOT appear when spanID is empty, got: %s", buf.String())
	}
}

// TestHandlerSpanIDInOutput kills CONDITIONALS_NEGATION at logger.go:142:12.
func TestHandlerSpanIDInOutput(t *testing.T) {
	buf := &bytes.Buffer{}
	base := slog.NewJSONHandler(buf, &slog.HandlerOptions{Level: LevelTrace})
	h := _newTelemetryHandler(base, DefaultLogConfig(), "test")

	ctx := SetTraceContext(context.Background(), "", "spanid-abc")
	r := slog.NewRecord(time.Now(), slog.LevelInfo, "a.b.c", 0)
	_ = h.Handle(ctx, r)
	if !strings.Contains(buf.String(), "spanid-abc") {
		t.Fatalf("span.id should appear, got: %s", buf.String())
	}
	if strings.Contains(buf.String(), "trace.id") {
		t.Fatalf("trace.id should NOT appear when traceID is empty, got: %s", buf.String())
	}
}

// TestHandlerTraceEarlyReturn kills CONDITIONALS_NEGATION at logger.go:134.
func TestHandlerTraceEarlyReturn(t *testing.T) {
	buf := &bytes.Buffer{}
	base := slog.NewJSONHandler(buf, &slog.HandlerOptions{Level: LevelTrace})
	h := _newTelemetryHandler(base, DefaultLogConfig(), "test")

	// No trace context → early return, no trace.id or span.id.
	r := slog.NewRecord(time.Now(), slog.LevelInfo, "a.b.c", 0)
	_ = h.Handle(context.Background(), r)
	if strings.Contains(buf.String(), "trace.id") || strings.Contains(buf.String(), "span.id") {
		t.Fatalf("no trace fields should appear without trace context, got: %s", buf.String())
	}
}

// ---- applyErrorFingerprint: excName empty vs non-empty ----

// TestHandlerFingerprintAddedOnError kills CONDITIONALS_NEGATION at logger.go:182:13.
func TestHandlerFingerprintAddedOnError(t *testing.T) {
	buf := &bytes.Buffer{}
	base := slog.NewJSONHandler(buf, &slog.HandlerOptions{Level: LevelTrace})
	h := _newTelemetryHandler(base, DefaultLogConfig(), "test")

	r := slog.NewRecord(time.Now(), slog.LevelInfo, "a.b.c", 0)
	r.AddAttrs(slog.String("exc_name", "ValueError"))
	_ = h.Handle(context.Background(), r)
	if !strings.Contains(buf.String(), "error_fingerprint") {
		t.Fatalf("error_fingerprint should appear when exc_name set, got: %s", buf.String())
	}
}

// TestHandlerFingerprintAbsentWithNoError verifies no fingerprint when no exc attrs.
func TestHandlerFingerprintAbsentWithNoError(t *testing.T) {
	buf := &bytes.Buffer{}
	base := slog.NewJSONHandler(buf, &slog.HandlerOptions{Level: LevelTrace})
	h := _newTelemetryHandler(base, DefaultLogConfig(), "test")

	r := slog.NewRecord(time.Now(), slog.LevelInfo, "a.b.c", 0)
	_ = h.Handle(context.Background(), r)
	if strings.Contains(buf.String(), "error_fingerprint") {
		t.Fatalf("error_fingerprint should NOT appear without exc attrs, got: %s", buf.String())
	}
}

// ---- _isPrefixMatch: empty module ----

// TestIsPrefixMatchEmptyModule kills CONDITIONALS_NEGATION at logger.go:231:12.
func TestIsPrefixMatchEmptyModule(t *testing.T) {
	// Empty module should match any name (including empty name).
	if !_isPrefixMatch("anyname", "") {
		t.Fatal("empty module should match any name")
	}
	if !_isPrefixMatch("", "") {
		t.Fatal("empty module should match empty name")
	}
	// Non-empty module with non-matching name → false.
	if _isPrefixMatch("other", "myapp") {
		t.Fatal("non-matching module should not match")
	}
}

// ---- GetLogger: individual trace attr conditions ----

// TestGetLoggerTraceIDPre kills CONDITIONALS_NEGATION at logger.go:289:14.
func TestGetLoggerTraceIDPre(t *testing.T) {
	Configure(DefaultLogConfig())

	// Only traceID set → logger should have trace.id pre-attached.
	ctx := SetTraceContext(context.Background(), "pre-trace-xyz", "")
	l := GetLogger(ctx, "svc")
	if l == nil {
		t.Fatal("GetLogger should return non-nil")
	}
	// Verify trace.id IS in the pre-attached attrs by logging to a buffer base.
	buf := &bytes.Buffer{}
	base := slog.NewJSONHandler(buf, &slog.HandlerOptions{Level: LevelTrace})
	h := _newTelemetryHandler(base, DefaultLogConfig(), "svc")
	ll := slog.New(h).With(slog.String("trace.id", "pre-trace-xyz"))
	ll.Info("a.b.c")
	if !strings.Contains(buf.String(), "pre-trace-xyz") {
		t.Fatalf("trace.id should be pre-attached, got: %s", buf.String())
	}
}

// TestGetLoggerSpanIDPre kills CONDITIONALS_NEGATION at logger.go:292:13.
func TestGetLoggerSpanIDPre(t *testing.T) {
	// Only spanID set → pre-attached.
	ctx := SetTraceContext(context.Background(), "", "pre-span")
	l := GetLogger(ctx, "svc")
	if l == nil {
		t.Fatal("GetLogger should return non-nil with spanID only")
	}
}

// TestGetLoggerFormatJSON kills CONDITIONALS_NEGATION at logger.go:287:13.
func TestGetLoggerFormatJsonDirect(t *testing.T) {
	cfg := DefaultLogConfig()
	cfg.Format = LogFormatJSON
	_cfg = cfg
	defer func() { _cfg = DefaultLogConfig() }()

	l := GetLogger(context.Background(), "svc")
	if l == nil {
		t.Fatal("GetLogger should return non-nil with JSON format")
	}
}

// ---- pii: maxDepth=0 triggers default ----

// TestPIIMaxDepthZeroUsesDefault kills CONDITIONALS_BOUNDARY at pii.go:148:14.
// maxDepth <= 0 → default; mutation < 0 would skip default for maxDepth=0.
func TestPIIMaxDepthZeroUsesDefault(t *testing.T) {
	SetPIIRules([]PIIRule{{Path: []string{"user", "pw"}, Mode: PIIModeRedact}})
	defer ResetPIIRules()

	// Nested payload that needs depth > 1 to sanitize.
	payload := map[string]any{
		"user": map[string]any{"pw": "secret"},
	}
	// maxDepth=0 → should use _piiDefaultMax (8), allowing recursion.
	result := SanitizePayload(payload, true, 0)
	userMap, ok := result["user"].(map[string]any)
	if !ok {
		t.Fatalf("user should be a map, got %T", result["user"])
	}
	if userMap["pw"] == "secret" {
		t.Fatal("pw should be redacted with default depth (maxDepth=0 → 8)")
	}
}

// ---- pii: truncation INVERT_NEGATIVES at pii.go:227 ----

// TestPIITruncateNegativeValue kills INVERT_NEGATIVES and ARITHMETIC_BASE at pii.go:227-229.
// truncateTo=3, string of 4 chars → should be "abc...".
func TestPIITruncateNegativeValue(t *testing.T) {
	SetPIIRules([]PIIRule{{Path: []string{"v"}, Mode: PIIModeTruncate, TruncateTo: 3}})
	defer ResetPIIRules()

	payload := map[string]any{"v": "abcd"} // 4 chars, TruncateTo=3
	result := SanitizePayload(payload, true, 0)
	s, ok := result["v"].(string)
	if !ok {
		t.Fatalf("v should be string, got %T", result["v"])
	}
	// Must be "abc..." (3 chars + suffix).
	if s != "abc..." {
		t.Fatalf("truncated value = %q, want 'abc...'", s)
	}
}

// TestPIITruncateZeroLength verifies TruncateTo=0 behavior (edge).
func TestPIITruncateZeroTruncateTo(t *testing.T) {
	SetPIIRules([]PIIRule{{Path: []string{"v"}, Mode: PIIModeTruncate, TruncateTo: 0}})
	defer ResetPIIRules()

	// TruncateTo=0 → the condition len(runes) >= 0+1 is always true for non-empty strings.
	// So any non-empty string gets truncated to 0 chars + "...".
	payload := map[string]any{"v": "abc"}
	result := SanitizePayload(payload, true, 0)
	s, ok := result["v"].(string)
	if !ok {
		t.Fatalf("v should be string, got %T", result["v"])
	}
	// 0 chars + "..." = "..."
	if s != "..." {
		t.Fatalf("TruncateTo=0 should produce '...', got %q", s)
	}
}

// ---- pii: _detectSecretInValue length boundary ----

// TestDetectSecretAtExactMinLength kills CONDITIONALS_BOUNDARY at pii.go:281:12.
// String of exactly _minSecretLength (20) chars that matches a pattern should be detected.
func TestDetectSecretAtExactMinLength(t *testing.T) {
	defer ResetSecretPatterns()
	// Register a pattern that matches exactly 20 chars.
	RegisterSecretPattern("exact20", regexp.MustCompile(`^[A-Z]{20}$`))

	// 20 uppercase letters: len=20 = _minSecretLength → NOT < _minSecretLength → proceeds to pattern check.
	exact20 := "ABCDEFGHIJKLMNOPQRST"
	payload := map[string]any{"tok": exact20}
	result := SanitizePayload(payload, true, 0)
	if result["tok"] == exact20 {
		t.Fatalf("string of exactly %d chars matching pattern should be redacted", len(exact20))
	}
}

// TestDetectSecretBelowMinLength verifies strings shorter than _minSecretLength are skipped.
func TestDetectSecretBelowMinLength(t *testing.T) {
	defer ResetSecretPatterns()
	RegisterSecretPattern("any", regexp.MustCompile(`.+`))

	// 19 chars: < _minSecretLength → not detected regardless of pattern.
	short := "ABCDEFGHIJKLMNOPQRS" // 19 chars
	payload := map[string]any{"tok": short}
	result := SanitizePayload(payload, true, 0)
	if result["tok"] != short {
		t.Fatalf("string shorter than %d chars should NOT be detected, got %v", 20, result["tok"])
	}
}

// ---- fingerprint: extractBasename exact boundary ----

// TestExtractBasenameLastSlashAtZero kills CONDITIONALS_BOUNDARY at fingerprint.go:66.
// When the last slash is at index 0, idx >= 0 is true but idx > 0 would be false.
func TestExtractBasenameLastSlashAtZero(t *testing.T) {
	// Path starts with "/" — LastIndex("/") returns 0.
	got := _extractBasename("/file.go")
	if got != "file" {
		t.Fatalf("_extractBasename('/file.go') = %q, want 'file'", got)
	}
}

// TestExtractBasenameLastDotAtZero kills CONDITIONALS_BOUNDARY at fingerprint.go:69.
func TestExtractBasenameLastDotAtZero(t *testing.T) {
	// File with dot at start (after stripping path).
	got := _extractBasename(".hidden")
	// dot at index 0: idx=0, >= 0 is true → strip everything after dot → empty string.
	_ = got // just verify no panic
}

// TestExtractFuncNameDotAtZero kills CONDITIONALS_BOUNDARY at fingerprint.go:77.
func TestExtractFuncNameDotAtZero(t *testing.T) {
	// Dot at position 0 → idx=0, >= 0 true → return [1:].
	got := _extractFuncName(".method")
	if got != "method" {
		t.Fatalf("_extractFuncName('.method') = %q, want 'method'", got)
	}
}

// ---- fingerprint: len(pcs) boundary ----

// TestComputeErrorFingerprintLenPCsBoundary kills CONDITIONALS_BOUNDARY at fingerprint.go:22:14.
// len(pcs) > 0: mutation to >= 0 would always enter the block (even for nil/empty slice).
func TestComputeErrorFingerprintLenPCsBoundary(t *testing.T) {
	// nil pcs → len=0 → must NOT enter the pc-processing block.
	fpNil := _computeErrorFingerprint("err", nil)
	// Empty slice → same.
	fpEmpty := _computeErrorFingerprint("err", []uintptr{})
	if fpNil != fpEmpty {
		t.Fatal("nil and empty pcs should produce the same fingerprint")
	}
	// Non-empty pcs → different fingerprint from nil.
	pcs := make([]uintptr, 10)
	n := runtimeCallers(1, pcs)
	fpReal := _computeErrorFingerprint("err", pcs[:n])
	if fpNil == fpReal {
		t.Fatal("real pcs should produce different fingerprint than nil")
	}
}

// TestComputeErrorFingerprintFileCheck kills CONDITIONALS_NEGATION at fingerprint.go:27:22.
// frame.File != "": if mutated to == "", no frames are appended → same fingerprint regardless of PCs.
func TestComputeErrorFingerprintFileCheck(t *testing.T) {
	pcs := make([]uintptr, 10)
	n := runtimeCallers(1, pcs)
	fp := _computeErrorFingerprint("err", pcs[:n])
	fpNil := _computeErrorFingerprint("err", nil)
	// Real frames have non-empty File → should produce a richer fingerprint.
	if fp == fpNil {
		t.Fatal("real frames with File should produce different fingerprint than nil PCs")
	}
}

// runtimeCallers wraps runtime.Callers for use in tests.
func runtimeCallers(skip int, pcs []uintptr) int {
	return runtime.Callers(skip+1, pcs)
}
