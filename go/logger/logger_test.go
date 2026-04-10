// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package logger_test

import (
	"bytes"
	"context"
	"log/slog"
	"regexp"
	"strings"
	"testing"

	"github.com/provide-io/provide-telemetry/go/logger"
)

// ---- helpers ----

type _bufHandler struct {
	buf   *bytes.Buffer
	level slog.Level
	attrs []slog.Attr
}

func (h *_bufHandler) Enabled(_ context.Context, l slog.Level) bool { return l >= h.level }
func (h *_bufHandler) Handle(_ context.Context, r slog.Record) error {
	h.buf.WriteString(r.Message)
	r.Attrs(func(a slog.Attr) bool { h.attrs = append(h.attrs, a); return true })
	return nil
}
func (h *_bufHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	cp := *h
	cp.attrs = append(cp.attrs, attrs...)
	return &cp
}
func (h *_bufHandler) WithGroup(name string) slog.Handler { return h }

func newBufHandler() (*_bufHandler, *bytes.Buffer) {
	buf := &bytes.Buffer{}
	return &_bufHandler{buf: buf, level: slog.LevelDebug - 10}, buf
}

func attrVal(attrs []slog.Attr, key string) (string, bool) {
	for _, a := range attrs {
		if a.Key == key {
			return a.Value.String(), true
		}
	}
	return "", false
}

// ---- errors ----

func TestErrors(t *testing.T) {
	terr := logger.NewTelemetryError("boom")
	if !strings.Contains(terr.Error(), "boom") {
		t.Fatalf("TelemetryError.Error() = %q, want 'boom'", terr.Error())
	}
	ce := logger.NewConfigurationError("bad config")
	if !strings.Contains(ce.Error(), "bad config") {
		t.Fatalf("ConfigurationError.Error() = %q, want 'bad config'", ce.Error())
	}
	ese := logger.NewEventSchemaError("bad event")
	if !strings.Contains(ese.Error(), "bad event") {
		t.Fatalf("EventSchemaError.Error() = %q, want 'bad event'", ese.Error())
	}
}

// ---- config ----

func TestDefaultLogConfig(t *testing.T) {
	cfg := logger.DefaultLogConfig()
	if cfg.Level != logger.LogLevelInfo {
		t.Fatalf("default level = %q, want INFO", cfg.Level)
	}
	if cfg.Format != logger.LogFormatConsole {
		t.Fatalf("default format = %q, want console", cfg.Format)
	}
}

// ---- context ----

func TestBindUnbindContext(t *testing.T) {
	ctx := context.Background()
	ctx = logger.BindContext(ctx, map[string]any{"k1": "v1", "k2": 2})
	fields := logger.GetBoundFields(ctx)
	if fields["k1"] != "v1" {
		t.Fatalf("k1 = %v, want v1", fields["k1"])
	}

	ctx = logger.UnbindContext(ctx, "k1")
	fields = logger.GetBoundFields(ctx)
	if _, ok := fields["k1"]; ok {
		t.Fatal("k1 should have been unbound")
	}
	if fields["k2"] == nil {
		t.Fatal("k2 should still be bound")
	}

	ctx = logger.ClearContext(ctx)
	if len(logger.GetBoundFields(ctx)) != 0 {
		t.Fatal("ClearContext should remove all fields")
	}
}

func TestGetBoundFieldsEmpty(t *testing.T) {
	ctx := context.Background()
	if len(logger.GetBoundFields(ctx)) != 0 {
		t.Fatal("fresh context should have no bound fields")
	}
}

func TestTraceContext(t *testing.T) {
	ctx := context.Background()
	traceID, spanID := logger.GetTraceContext(ctx)
	if traceID != "" || spanID != "" {
		t.Fatal("fresh context should have empty trace IDs")
	}

	ctx = logger.SetTraceContext(ctx, "abc123", "def456")
	traceID, spanID = logger.GetTraceContext(ctx)
	if traceID != "abc123" || spanID != "def456" {
		t.Fatalf("trace = %q, span = %q", traceID, spanID)
	}
}

func TestSessionContext(t *testing.T) {
	ctx := context.Background()
	if _, ok := logger.GetSessionID(ctx); ok {
		t.Fatal("fresh context should have no session")
	}

	ctx = logger.BindSessionContext(ctx, "sess-1")
	if id, ok := logger.GetSessionID(ctx); !ok || id != "sess-1" {
		t.Fatalf("session = %q, %v", id, ok)
	}

	ctx = logger.ClearSessionContext(ctx)
	if _, ok := logger.GetSessionID(ctx); ok {
		t.Fatal("cleared context should have no session")
	}
}

// ---- fingerprint ----

func TestComputeErrorFingerprintDeterministic(t *testing.T) {
	fp1 := logger.ComputeErrorFingerprintFromParts("ValueError", []string{"main:run"})
	fp2 := logger.ComputeErrorFingerprintFromParts("ValueError", []string{"main:run"})
	if fp1 != fp2 {
		t.Fatalf("fingerprint not deterministic: %q vs %q", fp1, fp2)
	}
	if len(fp1) != 12 {
		t.Fatalf("fingerprint length = %d, want 12", len(fp1))
	}
	// Different inputs should produce different fingerprints.
	fp3 := logger.ComputeErrorFingerprintFromParts("TypeError", []string{"main:run"})
	if fp1 == fp3 {
		t.Fatal("different error types should produce different fingerprints")
	}
}

// ---- schema ----

func TestEventName(t *testing.T) {
	name, err := logger.EventName(false, "auth", "login", "success")
	if err != nil || name != "auth.login.success" {
		t.Fatalf("EventName = %q, %v", name, err)
	}
	_, err = logger.EventName(false, "too", "few")
	if err == nil {
		t.Fatal("expected error for 2 segments")
	}
	_, err = logger.EventName(true, "auth", "Bad-Segment", "success")
	if err == nil {
		t.Fatal("expected error for invalid segment in strict mode")
	}
}

func TestEvent(t *testing.T) {
	rec, err := logger.Event(false, "auth", "login", "success")
	if err != nil || rec.Event != "auth.login.success" {
		t.Fatalf("Event = %+v, %v", rec, err)
	}
	// DARS form
	rec, err = logger.Event(false, "auth", "login", "user", "success")
	if err != nil || rec.Resource != "user" {
		t.Fatalf("DARS Event = %+v, %v", rec, err)
	}
	// Too many segments
	_, err = logger.Event(false, "a", "b", "c", "d", "e")
	if err == nil {
		t.Fatal("expected error for 5 segments in Event()")
	}
}

func TestValidateEventName(t *testing.T) {
	if err := logger.ValidateEventName(false, "a.b.c"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if err := logger.ValidateEventName(false, "a.b"); err == nil {
		t.Fatal("expected error for 2 segments")
	}
	if err := logger.ValidateEventName(true, "a.Bad.c"); err == nil {
		t.Fatal("expected error for invalid segment")
	}
}

func TestValidateRequiredKeys(t *testing.T) {
	attrs := map[string]any{"k1": "v1"}
	if err := logger.ValidateRequiredKeys(attrs, []string{"k1"}); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if err := logger.ValidateRequiredKeys(attrs, []string{"missing"}); err == nil {
		t.Fatal("expected error for missing key")
	}
}

// ---- PII ----

func TestSanitizePayloadDisabled(t *testing.T) {
	payload := map[string]any{"password": "secret123", "name": "alice"} // pragma: allowlist secret
	result := logger.SanitizePayload(payload, false, 0)
	if result["password"] != "secret123" { // pragma: allowlist secret
		t.Fatal("sanitize disabled should not redact")
	}
}

func TestSanitizePayloadDefaultKeys(t *testing.T) {
	payload := map[string]any{"password": "s3cr3t!", "name": "alice"} // pragma: allowlist secret
	result := logger.SanitizePayload(payload, true, 0)
	if result["password"] == "s3cr3t!" { // pragma: allowlist secret
		t.Fatal("password should be redacted")
	}
	if result["name"] != "alice" {
		t.Fatal("name should not be redacted")
	}
}

func TestPIIRules(t *testing.T) {
	defer logger.ResetPIIRules()

	logger.SetPIIRules([]logger.PIIRule{
		{Path: []string{"email"}, Mode: logger.PIIModeHash},
	})
	payload := map[string]any{"email": "user@example.com"}
	result := logger.SanitizePayload(payload, true, 0)
	val, ok := result["email"].(string)
	if !ok || len(val) != 12 {
		t.Fatalf("email hash = %v", result["email"])
	}
}

func TestSecretPatternRegistration(t *testing.T) {
	defer logger.ResetSecretPatterns()

	logger.RegisterSecretPattern("mytoken", regexp.MustCompile(`MYTOKEN-[A-Z0-9]{10,}`))
	patterns := logger.GetSecretPatterns()
	found := false
	for _, p := range patterns {
		if p.Name == "mytoken" {
			found = true
		}
	}
	if !found {
		t.Fatal("custom pattern not registered")
	}
}

// ---- logger handler ----

func TestConfigureAndGetLogger(t *testing.T) {
	cfg := logger.DefaultLogConfig()
	cfg.ServiceName = "test-svc"
	cfg.Level = logger.LogLevelDebug
	logger.Configure(cfg)

	if logger.Logger == nil {
		t.Fatal("Logger should be set after Configure")
	}
	if !logger.IsDebugEnabled() {
		t.Fatal("IsDebugEnabled should be true at DEBUG level")
	}
}

func TestIsTraceEnabled(t *testing.T) {
	cfg := logger.DefaultLogConfig()
	cfg.Level = logger.LogLevelTrace
	logger.Configure(cfg)
	if !logger.IsTraceEnabled() {
		t.Fatal("IsTraceEnabled should be true at TRACE level")
	}
}

func TestIsDebugEnabledNilLogger(t *testing.T) {
	orig := logger.Logger
	logger.Logger = nil
	if logger.IsDebugEnabled() {
		t.Fatal("IsDebugEnabled with nil Logger should return false")
	}
	if logger.IsTraceEnabled() {
		t.Fatal("IsTraceEnabled with nil Logger should return false")
	}
	logger.Logger = orig
}

func TestGetLoggerWithTraceContext(t *testing.T) {
	ctx := logger.SetTraceContext(context.Background(), "trace-1", "span-1")
	l := logger.GetLogger(ctx, "test")
	if l == nil {
		t.Fatal("GetLogger should not return nil")
	}
}

func TestGetLoggerNoTrace(t *testing.T) {
	l := logger.GetLogger(context.Background(), "test")
	if l == nil {
		t.Fatal("GetLogger should not return nil")
	}
}

func TestSamplingFunc(t *testing.T) {
	cfg := logger.DefaultLogConfig()
	logger.Configure(cfg)

	sampled := false
	logger.SetSamplingFunc(func(signal, key string) bool {
		if signal == "logs" {
			sampled = true
		}
		return true
	})
	defer logger.SetSamplingFunc(nil)

	logger.Logger.Info("test.event.ok")
	if !sampled {
		t.Fatal("sampling function should have been called")
	}
}

func TestSamplingFuncDrops(t *testing.T) {
	cfg := logger.DefaultLogConfig()
	logger.Configure(cfg)

	logger.SetSamplingFunc(func(signal, key string) bool { return false })
	defer logger.SetSamplingFunc(nil)

	// Should not panic; record is dropped silently.
	logger.Logger.Info("test.event.ok")
}

func TestStrictSchemaDropsInvalidEvent(t *testing.T) {
	cfg := logger.DefaultLogConfig()
	cfg.StrictSchema = true
	logger.Configure(cfg)
	defer func() {
		cfg.StrictSchema = false
		logger.Configure(cfg)
	}()

	// Message with invalid segment count should be dropped (no panic).
	logger.Logger.Info("not_a_valid_event")
}

func TestModuleLevelOverride(t *testing.T) {
	cfg := logger.DefaultLogConfig()
	cfg.Level = logger.LogLevelError
	cfg.ModuleLevels = map[string]string{"myapp": logger.LogLevelDebug}
	logger.Configure(cfg)

	l := logger.GetLogger(context.Background(), "myapp.service")
	if !l.Enabled(context.Background(), slog.LevelDebug) {
		t.Fatal("myapp.service should be enabled at DEBUG via module override")
	}
}

func TestGetDefaultLogger(t *testing.T) {
	cfg := logger.DefaultLogConfig()
	cfg.ServiceName = "default-test"
	logger.Configure(cfg)

	l := logger.GetDefaultLogger("mypackage.service")
	if l == nil {
		t.Fatal("GetDefaultLogger should return non-nil logger")
	}
	// Calling it twice should return loggers that behave identically
	// (evaluated at call time, not cached).
	l2 := logger.GetDefaultLogger("mypackage.service")
	if l2 == nil {
		t.Fatal("second call to GetDefaultLogger should also return non-nil")
	}
	// Loggers from GetDefaultLogger reflect the active config, so debug should
	// be disabled here (level is INFO by default after Configure).
	cfg2 := logger.DefaultLogConfig()
	cfg2.Level = logger.LogLevelInfo
	logger.Configure(cfg2)
	lInfo := logger.GetDefaultLogger("mypackage.service")
	if lInfo.Enabled(nil, slog.LevelDebug) { //nolint:staticcheck // nil ctx is valid in tests
		t.Fatal("GetDefaultLogger at INFO level should not be enabled for DEBUG")
	}
}

func TestContextFieldsApplied(t *testing.T) {
	cfg := logger.DefaultLogConfig()
	cfg.Level = logger.LogLevelDebug
	logger.Configure(cfg)

	ctx := logger.BindContext(context.Background(), map[string]any{"req_id": "abc"})
	l := logger.GetLogger(ctx, "test")
	// Just ensure no panic; the bound field propagation is exercised.
	l.InfoContext(ctx, "test.context.ok")
}

func TestEventRecordAttrs(t *testing.T) {
	rec, err := logger.Event(false, "auth", "login", "user", "success")
	if err != nil {
		t.Fatalf("Event error: %v", err)
	}
	attrs := rec.Attrs()
	found := map[string]bool{}
	for _, a := range attrs {
		if s, ok := a.(slog.Attr); ok {
			found[s.Key] = true
		}
	}
	// Attrs() returns []any but internally slog.Attr pairs — just check no panic.
	if len(attrs) == 0 {
		t.Fatal("Attrs should not be empty")
	}
}
