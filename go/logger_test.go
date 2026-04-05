// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"os"
	"strings"
	"testing"
	"time"
)

// newTestLogger builds a *slog.Logger writing JSON to buf through _telemetryHandler.
func newTestLogger(buf *bytes.Buffer, cfg *TelemetryConfig, name string) *slog.Logger {
	base := slog.NewJSONHandler(buf, &slog.HandlerOptions{Level: LevelTrace})
	h := _newTelemetryHandler(base, cfg, name)
	return slog.New(h)
}

// setupFullSampling ensures all log records pass sampling during a test.
func setupFullSampling(t *testing.T) {
	t.Helper()
	_resetSamplingPolicies()
	SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 1.0})
	t.Cleanup(_resetSamplingPolicies)
}

// ── 1. GetLogger returns non-nil ─────────────────────────────────────────────

func TestGetLogger_NotNil(t *testing.T) {
	l := GetLogger(context.Background(), "test")
	if l == nil {
		t.Fatal("GetLogger returned nil")
	}
}

// ── 2/3. IsDebugEnabled / IsTraceEnabled with DEBUG/TRACE config ─────────────

func TestIsDebugEnabled_WithDebugConfig(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Level = "DEBUG"
	_configureLogger(cfg)
	t.Cleanup(func() { _configureLogger(DefaultTelemetryConfig()) })

	if !IsDebugEnabled() {
		t.Error("expected IsDebugEnabled true for DEBUG level")
	}
}

func TestIsTraceEnabled_WithTraceConfig(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Level = "TRACE"
	_configureLogger(cfg)
	t.Cleanup(func() { _configureLogger(DefaultTelemetryConfig()) })

	if !IsTraceEnabled() {
		t.Error("expected IsTraceEnabled true for TRACE level")
	}
}

// ── 3. IsTraceEnabled with INFO-level config (should be false) ───────────────

func TestIsTraceEnabled_WithInfoConfig(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Level = "INFO"
	_configureLogger(cfg)
	t.Cleanup(func() { _configureLogger(DefaultTelemetryConfig()) })

	if IsTraceEnabled() {
		t.Error("expected IsTraceEnabled false for INFO level")
	}
}

// ── nil Logger guards ────────────────────────────────────────────────────────

func TestIsDebugEnabled_NilLogger(t *testing.T) {
	orig := Logger
	Logger = nil
	t.Cleanup(func() { Logger = orig })

	if IsDebugEnabled() {
		t.Error("expected IsDebugEnabled false when Logger is nil")
	}
}

func TestIsTraceEnabled_NilLogger(t *testing.T) {
	orig := Logger
	Logger = nil
	t.Cleanup(func() { Logger = orig })

	if IsTraceEnabled() {
		t.Error("expected IsTraceEnabled false when Logger is nil")
	}
}

// ── 4. Standard fields (service.name / .env / .version) ─────────────────────

func TestHandler_StandardFields(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.ServiceName = "svc-a"
	cfg.Environment = "prod"
	cfg.Version = "1.2.3"
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("hello")

	out := buf.String()
	for _, want := range []string{`"service.name":"svc-a"`, `"service.env":"prod"`, `"service.version":"1.2.3"`} {
		if !strings.Contains(out, want) {
			t.Errorf("missing %s in output: %s", want, out)
		}
	}
}

func TestHandler_NoStandardFields_WhenEmpty(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.ServiceName = ""
	cfg.Environment = ""
	cfg.Version = ""
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("no std fields")

	if strings.Contains(buf.String(), "service.name") {
		t.Errorf("unexpected service.name in output: %s", buf.String())
	}
}

// ── 5. Context fields from BindContext ────────────────────────────────────────

func TestHandler_ContextFields(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")

	ctx := BindContext(context.Background(), map[string]any{"request_id": "abc123"})
	l.InfoContext(ctx, "ctx test")

	out := buf.String()
	if !strings.Contains(out, "request_id") || !strings.Contains(out, "abc123") {
		t.Errorf("missing context fields in output: %s", out)
	}
}

// ── 6. Sampling drop ─────────────────────────────────────────────────────────

func TestHandler_SamplingDrop(t *testing.T) {
	_resetSamplingPolicies()
	SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 0.0})
	t.Cleanup(_resetSamplingPolicies)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("should be dropped")

	if buf.Len() != 0 {
		t.Errorf("expected empty buffer when sampling=0, got: %s", buf.String())
	}
}

// ── 7. PII sanitization ───────────────────────────────────────────────────────

func TestHandler_PIISanitization(t *testing.T) {
	setupFullSampling(t)

	SetPIIRules([]PIIRule{{Path: []string{"secret_val"}, Mode: PIIModeRedact}})
	t.Cleanup(_resetPIIRules)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = true

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("pii test", slog.String("secret_val", "my-secret"))

	out := buf.String()
	if strings.Contains(out, "my-secret") {
		t.Errorf("PII value leaked in output: %s", out)
	}
	if !strings.Contains(out, "***") {
		t.Errorf("expected redacted marker in output: %s", out)
	}
}

func TestHandler_PIISanitize_Disabled(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("no pii", slog.String("password", "s3cr3t"))

	// When sanitize=false, SanitizePayload returns a shallow copy unchanged.
	out := buf.String()
	if !strings.Contains(out, "s3cr3t") {
		t.Errorf("expected unsanitized password in output when sanitize=false: %s", out)
	}
}

// ── 8. Per-module override: DEBUG emitted ─────────────────────────────────────

func TestHandler_ModuleLevelOverride_Emits(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Level = "INFO"
	cfg.Logging.ModuleLevels = map[string]string{"mymodule": "DEBUG"}
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "mymodule")
	l.Debug("debug msg")

	if buf.Len() == 0 {
		t.Error("expected debug log to be emitted for mymodule override")
	}
}

// ── 9. Per-module override: DEBUG suppressed for different module ─────────────

func TestHandler_ModuleLevelOverride_Suppresses(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Level = "INFO"
	cfg.Logging.ModuleLevels = map[string]string{"mymodule": "DEBUG"}
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "other")
	l.Debug("debug msg")

	if buf.Len() != 0 {
		t.Errorf("expected debug log suppressed for 'other' module: %s", buf.String())
	}
}

// ── 10/11. _configureLogger JSON and text formats ────────────────────────────

func TestConfigureLogger_JSONFormat(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Format = "json"
	_configureLogger(cfg)
	t.Cleanup(func() { _configureLogger(DefaultTelemetryConfig()) })

	if Logger == nil {
		t.Fatal("Logger is nil after _configureLogger with json format")
	}
}

func TestConfigureLogger_TextFormat(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Format = "console"
	_configureLogger(cfg)
	t.Cleanup(func() { _configureLogger(DefaultTelemetryConfig()) })

	if Logger == nil {
		t.Fatal("Logger is nil after _configureLogger with text format")
	}
}

// ── 12. Logger package var set after _configureLogger ────────────────────────

func TestLoggerPackageVar_SetAfterConfigure(t *testing.T) {
	prev := Logger
	cfg := DefaultTelemetryConfig()
	_configureLogger(cfg)
	t.Cleanup(func() { Logger = prev })

	if Logger == nil {
		t.Fatal("Logger package var not set after _configureLogger")
	}
}

// ── Additional coverage ──────────────────────────────────────────────────────

func TestGetLogger_UsesConfiguredLogger(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Format = "json"
	_configureLogger(cfg)
	t.Cleanup(func() { _configureLogger(DefaultTelemetryConfig()) })

	l := GetLogger(context.Background(), "sub.module")
	if l == nil {
		t.Fatal("GetLogger returned nil when Logger is configured")
	}
}

func TestGetLogger_FallbackWhenNilLogger(t *testing.T) {
	orig := Logger
	Logger = nil
	t.Cleanup(func() { Logger = orig })

	l := GetLogger(context.Background(), "fallback")
	if l == nil {
		t.Fatal("GetLogger returned nil with nil Logger")
	}
}

func TestGetLogger_NonTelemetryHandler(t *testing.T) {
	orig := Logger
	// Set Logger to a plain slog.Logger (not backed by _telemetryHandler)
	Logger = slog.Default()
	t.Cleanup(func() { Logger = orig })

	l := GetLogger(context.Background(), "plain")
	if l == nil {
		t.Fatal("GetLogger returned nil when Logger has non-telemetry handler")
	}
}

func TestHandler_WithAttrs(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l2 := l.With("persistent_key", "persistent_val")
	l2.Info("with attrs test")

	if !strings.Contains(buf.String(), "persistent_key") {
		t.Errorf("missing persistent_key in output: %s", buf.String())
	}
}

func TestHandler_WithGroup(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l2 := l.WithGroup("mygroup")
	l2.Info("group test", slog.String("k", "v"))

	if !strings.Contains(buf.String(), "mygroup") {
		t.Errorf("missing group name in output: %s", buf.String())
	}
}

func TestHandler_SchemaStrict_Drop(t *testing.T) {
	_strictSchema = true
	t.Cleanup(func() { _strictSchema = false })
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	// Not a valid dotted event name (fails segment-count validation)
	l.Info("invalid")

	if buf.Len() != 0 {
		t.Errorf("expected strict schema to drop invalid event, got: %s", buf.String())
	}
}

func TestHandler_SchemaStrict_Valid(t *testing.T) {
	_strictSchema = true
	t.Cleanup(func() { _strictSchema = false })
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("user.auth.login")

	if buf.Len() == 0 {
		t.Error("expected valid event name to pass strict schema")
	}
}

func TestHandler_JSONOutput_Parseable(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.ServiceName = "parse-test"
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("parseable")

	var m map[string]any
	if err := json.Unmarshal(buf.Bytes(), &m); err != nil {
		t.Fatalf("output not valid JSON: %v\noutput: %s", err, buf.String())
	}
	if m["service.name"] != "parse-test" {
		t.Errorf("expected service.name=parse-test, got %v", m["service.name"])
	}
}

func TestEffectiveLevel_PrefixMatch(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Level = "INFO"
	cfg.Logging.ModuleLevels = map[string]string{
		"provide":           "WARN",
		"provide.telemetry": "DEBUG",
	}

	level := _effectiveLevel("provide.telemetry.auth", cfg)
	if level != slog.LevelDebug {
		t.Errorf("expected DEBUG from longest prefix match, got %v", level)
	}
}

func TestEffectiveLevel_NilConfig(t *testing.T) {
	level := _effectiveLevel("anything", nil)
	if level != slog.LevelInfo {
		t.Errorf("expected INFO for nil config, got %v", level)
	}
}

func TestParseLevel_AllVariants(t *testing.T) {
	cases := []struct {
		input    string
		expected slog.Level
	}{
		{"TRACE", LevelTrace},
		{"DEBUG", slog.LevelDebug},
		{"INFO", slog.LevelInfo},
		{"WARN", slog.LevelWarn},
		{"WARNING", slog.LevelWarn},
		{"ERROR", slog.LevelError},
		{"CRITICAL", slog.LevelError},
		{"unknown", slog.LevelInfo},
		{"", slog.LevelInfo},
	}
	for _, tc := range cases {
		got := _parseLevel(tc.input)
		if got != tc.expected {
			t.Errorf("_parseLevel(%q) = %v, want %v", tc.input, got, tc.expected)
		}
	}
}

func TestIsPrefixMatch(t *testing.T) {
	cases := []struct {
		name, module string
		want         bool
	}{
		{"a.b.c", "a.b", true},
		{"a.b", "a.b", true},
		{"anything", "", true},
		{"ab.c", "a", false},
		{"other", "mymodule", false},
	}
	for _, tc := range cases {
		got := _isPrefixMatch(tc.name, tc.module)
		if got != tc.want {
			t.Errorf("_isPrefixMatch(%q, %q) = %v, want %v", tc.name, tc.module, got, tc.want)
		}
	}
}

func TestAttrsToMap_AndMapToAttrs(t *testing.T) {
	rec := slog.NewRecord(time.Now(), slog.LevelInfo, "msg", 0)
	rec.AddAttrs(slog.String("foo", "bar"), slog.Int("n", 42))

	m := _attrsToMap(rec)
	if m["foo"] != "bar" {
		t.Errorf("expected foo=bar, got %v", m["foo"])
	}
	if m["n"] != int64(42) {
		t.Errorf("expected n=42, got %v (%T)", m["n"], m["n"])
	}

	attrs := _mapToAttrs(m)
	found := map[string]bool{}
	for _, a := range attrs {
		found[a.Key] = true
	}
	if !found["foo"] || !found["n"] {
		t.Errorf("round-trip lost keys: got %v", found)
	}
}

func TestGetTraceSpanFromContext_ReturnsEmpty(t *testing.T) {
	traceID, spanID := _getTraceSpanFromContext(context.Background())
	if traceID != "" || spanID != "" {
		t.Errorf("expected empty trace/span IDs, got %q %q", traceID, spanID)
	}
}

// ── Trace/span ID injection ───────────────────────────────────────────────────

func TestHandler_TraceSpanFields(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")

	ctx := SetTraceContext(context.Background(), "trace-abc", "span-xyz")
	l.InfoContext(ctx, "with trace")

	out := buf.String()
	if !strings.Contains(out, "trace-abc") {
		t.Errorf("missing trace.id in output: %s", out)
	}
	if !strings.Contains(out, "span-xyz") {
		t.Errorf("missing span.id in output: %s", out)
	}
}

func TestHandler_TraceIDOnly(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")

	ctx := SetTraceContext(context.Background(), "trace-only", "")
	l.InfoContext(ctx, "trace only")

	out := buf.String()
	if !strings.Contains(out, "trace-only") {
		t.Errorf("missing trace.id in output: %s", out)
	}
}

func TestHandler_SpanIDOnly(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")

	ctx := SetTraceContext(context.Background(), "", "span-only")
	l.InfoContext(ctx, "span only")

	out := buf.String()
	if !strings.Contains(out, "span-only") {
		t.Errorf("missing span.id in output: %s", out)
	}
}

// ── clone() branch coverage — non-empty attrs/groups ─────────────────────────

func TestHandler_Clone_NonEmptyAttrs(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	base := slog.NewJSONHandler(&buf, &slog.HandlerOptions{Level: LevelTrace})
	h := &_telemetryHandler{next: base, cfg: cfg, name: ""}

	// First WithAttrs: clone called with empty attrs (false branch in clone).
	h2 := h.WithAttrs([]slog.Attr{slog.String("k1", "v1")})

	// Second WithAttrs: clone called when h already has attrs (true branch in clone).
	h3 := h2.WithAttrs([]slog.Attr{slog.String("k2", "v2")})
	slog.New(h3).Info("double with attrs")

	out := buf.String()
	if !strings.Contains(out, "k1") || !strings.Contains(out, "k2") {
		t.Errorf("missing attrs in output: %s", out)
	}
}

func TestHandler_Clone_NonEmptyGroups(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	base := slog.NewJSONHandler(&buf, &slog.HandlerOptions{Level: LevelTrace})
	h := &_telemetryHandler{next: base, cfg: cfg, name: ""}

	// First WithGroup: clone called with empty groups (false branch in clone).
	h2 := h.WithGroup("g1")

	// Second WithGroup: clone called when h already has groups (true branch in clone).
	h3 := h2.WithGroup("g2")
	slog.New(h3).Info("double group", slog.String("k", "v"))

	out := buf.String()
	if !strings.Contains(out, "g1") {
		t.Errorf("missing g1 in output: %s", out)
	}
}

// ── applyContextFields — pre-existing record attrs preserved ─────────────────

func TestHandler_ContextFields_WithExistingAttrs(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")

	ctx := BindContext(context.Background(), map[string]any{"ctx_key": "ctx_val"})
	// Pass extra attrs with the log call so r.Attrs is non-empty in applyContextFields.
	l.InfoContext(ctx, "ctx with attrs", slog.String("inline_key", "inline_val"))

	out := buf.String()
	if !strings.Contains(out, "ctx_key") {
		t.Errorf("missing ctx_key in output: %s", out)
	}
	if !strings.Contains(out, "inline_key") {
		t.Errorf("missing inline_key in output: %s", out)
	}
}

// ── applyStandardFields partial-set: kills CONDITIONALS_NEGATION mutations ───
// logger.go:103 condition: ServiceName == "" && Environment == "" && Version == ""
// Mutation col 21: ServiceName != "" — with ServiceName set and others empty,
// mutant returns early (skips all fields). Test verifies service.name IS present.
func TestHandler_StandardField_OnlyServiceName(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.ServiceName = "only-svc"
	cfg.Environment = ""
	cfg.Version = ""
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("partial std fields")

	out := buf.String()
	if !strings.Contains(out, `"service.name":"only-svc"`) {
		t.Errorf("expected service.name in output, got: %s", out)
	}
	if strings.Contains(out, "service.env") {
		t.Errorf("unexpected service.env when Environment is empty: %s", out)
	}
}

// Mutation col 67: Version != "" — with Version set and others empty,
// mutant returns early. Test verifies service.version IS present.
func TestHandler_StandardField_OnlyVersion(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.ServiceName = ""
	cfg.Environment = ""
	cfg.Version = "1.0.0"
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("version only")

	out := buf.String()
	if !strings.Contains(out, `"service.version":"1.0.0"`) {
		t.Errorf("expected service.version in output, got: %s", out)
	}
}

// Mutation col 46: Environment != "" — with Environment set and others empty,
// mutant returns early. Test verifies service.env IS present.
func TestHandler_StandardField_OnlyEnvironment(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.ServiceName = ""
	cfg.Environment = "staging"
	cfg.Version = ""
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("env only")

	out := buf.String()
	if !strings.Contains(out, `"service.env":"staging"`) {
		t.Errorf("expected service.env in output, got: %s", out)
	}
}

// ── _effectiveLevel: modules differing by 1 char ─────────────────────────────
// logger.go:188 `len(module) >= bestLen+1` BOUNDARY: `> bestLen+1` would skip
// module "ab" (len=2) when bestLen=1 because 2 > 2 is false.
func TestEffectiveLevel_ConsecutiveLengthModules(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Level = "INFO"
	cfg.Logging.ModuleLevels = map[string]string{
		"a":  "WARN",
		"ab": "DEBUG",
	}
	// "ab.c" matches both "a" (prefix) and "ab" (prefix).
	// "ab" is longer → should win with DEBUG.
	level := _effectiveLevel("ab.c", cfg)
	if level != slog.LevelDebug {
		t.Errorf("expected DEBUG from longest prefix 'ab', got %v", level)
	}
}

// ── _effectiveLevel: empty module key ────────────────────────────────────────
func TestEffectiveLevel_EmptyModuleKey_MatchesAll(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Level = "INFO"
	cfg.Logging.ModuleLevels = map[string]string{"": "DEBUG"}

	level := _effectiveLevel("any.module.name", cfg)
	if level != slog.LevelDebug {
		t.Errorf("empty module key should match all names; want DEBUG, got %v", level)
	}
}

// ── _configureLogger produces JSON output when format=json ───────────────────
// Tests observable behavior: logger output must be valid JSON, not just the handler type.
func TestConfigureLogger_JSONFormat_ProducesJSON(t *testing.T) {
	setupFullSampling(t)

	r, w, _ := os.Pipe()
	origStderr := os.Stderr
	os.Stderr = w
	defer func() { os.Stderr = origStderr }()

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Format = LogFormatJSON
	cfg.ServiceName = "json-pipe-test"
	cfg.Logging.Sanitize = false
	_configureLogger(cfg)
	t.Cleanup(func() { _configureLogger(DefaultTelemetryConfig()) })

	Logger.Info("format check")
	_ = w.Close()

	var buf bytes.Buffer
	_, _ = buf.ReadFrom(r)
	out := buf.String()

	var m map[string]any
	if err := json.Unmarshal([]byte(out), &m); err != nil {
		t.Fatalf("_configureLogger with JSON format produced non-JSON output: %v\noutput: %s", err, out)
	}
}

// ── Error fingerprint injection ───────────────────────────────────────────────

func TestHandler_ErrorFingerprint_Added(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("error occurred", slog.String("exc_name", "ValueError"))

	out := buf.String()
	if !strings.Contains(out, "error_fingerprint") {
		t.Errorf("expected error_fingerprint in output: %s", out)
	}
}

func TestHandler_ErrorFingerprint_NotAdded_WhenNoError(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("normal message")

	if strings.Contains(buf.String(), "error_fingerprint") {
		t.Errorf("unexpected error_fingerprint in output: %s", buf.String())
	}
}

// ── Schema strict: required keys drop / pass ──────────────────────────────────

func TestHandler_SchemaStrict_RequiredKeys_Drop(t *testing.T) {
	_strictSchema = true
	t.Cleanup(func() { _strictSchema = false })
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.EventSchema.RequiredKeys = []string{"domain"}
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("user.auth.login")

	if buf.Len() != 0 {
		t.Errorf("expected record dropped for missing required key, got: %s", buf.String())
	}
}

func TestHandler_SchemaStrict_RequiredKeys_Pass(t *testing.T) {
	_strictSchema = true
	t.Cleanup(func() { _strictSchema = false })
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.EventSchema.RequiredKeys = []string{"domain"}
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("user.auth.login", slog.String("domain", "user"))

	if buf.Len() == 0 {
		t.Error("expected record to pass when required key is present")
	}
}

// ── GetLogger produces JSON output when format=json ─────────────────────────
func TestGetLogger_JSONFormat_ProducesJSON(t *testing.T) {
	setupFullSampling(t)

	r, w, _ := os.Pipe()
	origStderr := os.Stderr
	os.Stderr = w
	defer func() { os.Stderr = origStderr }()

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Format = LogFormatJSON
	cfg.Logging.Sanitize = false
	_configureLogger(cfg)
	t.Cleanup(func() { _configureLogger(DefaultTelemetryConfig()) })

	l := GetLogger(context.Background(), "json-pipe-test")
	l.Info("format check")
	_ = w.Close()

	var buf bytes.Buffer
	_, _ = buf.ReadFrom(r)
	out := buf.String()

	var m map[string]any
	if err := json.Unmarshal([]byte(out), &m); err != nil {
		t.Fatalf("GetLogger with JSON format produced non-JSON output: %v\noutput: %s", err, out)
	}
}
