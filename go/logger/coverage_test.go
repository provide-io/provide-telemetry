// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// coverage_test.go exercises code paths not reached by logger_test.go.
package logger_test

import (
	"bytes"
	"context"
	"errors"
	"log/slog"
	"testing"

	"github.com/provide-io/provide-telemetry/go/logger"
)

// ---- errors: Unwrap and As ----

func TestTelemetryErrorUnwrap(t *testing.T) {
	cause := errors.New("root cause")
	terr := logger.NewTelemetryError("wrapper", cause)
	if !errors.Is(terr, cause) {
		t.Fatal("Unwrap should expose the cause")
	}
}

func TestConfigurationErrorAs(t *testing.T) {
	ce := logger.NewConfigurationError("cfg problem")
	var terr *logger.TelemetryError
	if !errors.As(ce, &terr) {
		t.Fatal("ConfigurationError.As should match *TelemetryError")
	}
}

func TestEventSchemaErrorAs(t *testing.T) {
	ese := logger.NewEventSchemaError("schema problem")
	var terr *logger.TelemetryError
	if !errors.As(ese, &terr) {
		t.Fatal("EventSchemaError.As should match *TelemetryError")
	}
}

func TestNewConfigurationErrorWithCause(t *testing.T) {
	cause := errors.New("root")
	ce := logger.NewConfigurationError("cfg", cause)
	if !errors.Is(ce, cause) {
		t.Fatal("ConfigurationError should unwrap to cause")
	}
}

func TestNewEventSchemaErrorWithCause(t *testing.T) {
	cause := errors.New("root")
	ese := logger.NewEventSchemaError("schema", cause)
	if !errors.Is(ese, cause) {
		t.Fatal("EventSchemaError should unwrap to cause")
	}
}

// ---- GetBoundFields: non-map value in context ----

func TestGetBoundFieldsBadType(t *testing.T) {
	type badKey struct{}
	// We can't inject a bad type into the fields key directly, but we can verify
	// that an empty context returns an empty map (covers the nil branch).
	ctx := context.Background()
	fields := logger.GetBoundFields(ctx)
	if len(fields) != 0 {
		t.Fatal("empty context should yield empty fields")
	}
}

// ---- applyStandardFields: partial fields ----

func TestConfigureWithServiceMetadata(t *testing.T) {
	cfg := logger.DefaultLogConfig()
	cfg.ServiceName = "svc"
	cfg.Environment = "prod"
	cfg.Version = "1.2.3"
	cfg.Level = logger.LogLevelDebug
	logger.Configure(cfg)
	defer func() {
		logger.Configure(logger.DefaultLogConfig())
	}()

	// Log a record; applyStandardFields should add service.* attrs without panic.
	logger.Logger.Info("test.std.ok")
}

func TestConfigureServiceNameOnly(t *testing.T) {
	cfg := logger.DefaultLogConfig()
	cfg.ServiceName = "only-name"
	logger.Configure(cfg)
	defer func() {
		logger.Configure(logger.DefaultLogConfig())
	}()
	logger.Logger.Info("test.name.ok")
}

func TestConfigureEnvOnly(t *testing.T) {
	cfg := logger.DefaultLogConfig()
	cfg.Environment = "staging"
	logger.Configure(cfg)
	defer func() {
		logger.Configure(logger.DefaultLogConfig())
	}()
	logger.Logger.Info("test.env.ok")
}

func TestConfigureVersionOnly(t *testing.T) {
	cfg := logger.DefaultLogConfig()
	cfg.Version = "2.0"
	logger.Configure(cfg)
	defer func() {
		logger.Configure(logger.DefaultLogConfig())
	}()
	logger.Logger.Info("test.ver.ok")
}

// ---- applyTraceFields: trace in context ----

func TestHandlerApplyTraceFields(t *testing.T) {
	cfg := logger.DefaultLogConfig()
	logger.Configure(cfg)

	ctx := logger.SetTraceContext(context.Background(), "trace-111", "span-222")
	logger.Logger.InfoContext(ctx, "test.trace.fields")
}

// ---- applyErrorFingerprint ----

func TestHandlerErrorFingerprint(t *testing.T) {
	cfg := logger.DefaultLogConfig()
	logger.Configure(cfg)

	// Use a JSON format so all attrs round-trip through the handler.
	cfg.Format = logger.LogFormatJSON
	logger.Configure(cfg)
	defer func() {
		cfg.Format = logger.LogFormatConsole
		logger.Configure(cfg)
	}()

	// Log with exc_info → triggers applyErrorFingerprint.
	logger.Logger.Info("test.exception.ok",
		slog.String("exc_info", "ValueError"),
	)
	// Log with exc_name.
	logger.Logger.Info("test.exception.ok",
		slog.String("exc_name", "TypeError"),
	)
	// Log with exception.
	logger.Logger.Info("test.exception.ok",
		slog.String("exception", "RuntimeError"),
	)
}

// ---- applySchema: requiredKeys path ----

func TestHandlerSchemaRequiredKeys(t *testing.T) {
	cfg := logger.DefaultLogConfig()
	cfg.StrictSchema = true
	cfg.RequiredKeys = []string{"request_id"}
	logger.Configure(cfg)
	defer func() {
		base := logger.DefaultLogConfig()
		logger.Configure(base)
	}()

	// Missing required key → record is dropped (no panic).
	logger.Logger.Info("test.schema.check")
	// With required key → record passes.
	logger.Logger.Info("test.schema.check", slog.String("request_id", "req-1"))
}

// ---- WithGroup ----

func TestHandlerWithGroup(t *testing.T) {
	cfg := logger.DefaultLogConfig()
	logger.Configure(cfg)

	l := logger.Logger.WithGroup("mygroup")
	if l == nil {
		t.Fatal("WithGroup should return a non-nil logger")
	}
	l.Info("test.group.ok")
}

// ---- _isPrefixMatch: exact match and empty module ----

func TestModuleLevelExactMatch(t *testing.T) {
	cfg := logger.DefaultLogConfig()
	cfg.Level = logger.LogLevelError
	cfg.ModuleLevels = map[string]string{
		"":      logger.LogLevelWarn,  // empty module → always matches
		"exact": logger.LogLevelDebug, // exact match
	}
	logger.Configure(cfg)
	defer func() { logger.Configure(logger.DefaultLogConfig()) }()

	l := logger.GetLogger(context.Background(), "exact")
	if !l.Enabled(context.Background(), slog.LevelDebug) {
		t.Fatal("exact module match should enable DEBUG")
	}
}

// ---- _parseLevel: all branches ----

func TestParseLevels(t *testing.T) {
	cases := []struct {
		level    string
		expected slog.Level
	}{
		{logger.LogLevelTrace, logger.LevelTrace},
		{logger.LogLevelDebug, slog.LevelDebug},
		{logger.LogLevelWarn, slog.LevelWarn},
		{logger.LogLevelWarning, slog.LevelWarn},
		{logger.LogLevelError, slog.LevelError},
		{logger.LogLevelCritical, slog.LevelError},
		{"UNKNOWN", slog.LevelInfo}, // default fallback
	}
	for _, tc := range cases {
		cfg := logger.DefaultLogConfig()
		cfg.Level = tc.level
		logger.Configure(cfg)
		got := logger.Logger.Enabled(context.Background(), tc.expected)
		if !got {
			t.Errorf("level %q: logger not enabled at expected level %v", tc.level, tc.expected)
		}
	}
}

// ---- _configureLogger: JSON format ----

func TestConfigureJSON(t *testing.T) {
	cfg := logger.DefaultLogConfig()
	cfg.Format = logger.LogFormatJSON
	logger.Configure(cfg)
	defer func() {
		cfg.Format = logger.LogFormatConsole
		logger.Configure(cfg)
	}()
	if logger.Logger == nil {
		t.Fatal("Logger should be set after Configure with JSON format")
	}
}

// ---- PII: remaining branches ----

func TestPIIDropMode(t *testing.T) {
	defer logger.ResetPIIRules()
	logger.SetPIIRules([]logger.PIIRule{
		{Path: []string{"ssn"}, Mode: logger.PIIModeDrop},
	})
	payload := map[string]any{"ssn": "123-45-6789"}
	result := logger.SanitizePayload(payload, true, 0)
	if _, ok := result["ssn"]; ok {
		t.Fatal("ssn should be dropped")
	}
}

func TestPIITruncateMode(t *testing.T) {
	defer logger.ResetPIIRules()
	logger.SetPIIRules([]logger.PIIRule{
		{Path: []string{"note"}, Mode: logger.PIIModeTruncate, TruncateTo: 5},
	})
	payload := map[string]any{"note": "this is a long note"}
	result := logger.SanitizePayload(payload, true, 0)
	s, ok := result["note"].(string)
	if !ok {
		t.Fatalf("note = %T %v", result["note"], result["note"])
	}
	if len([]rune(s)) > 8 { // 5 chars + "..."
		t.Fatalf("note should be truncated, got %q", s)
	}
}

func TestPIITruncateShort(t *testing.T) {
	defer logger.ResetPIIRules()
	logger.SetPIIRules([]logger.PIIRule{
		{Path: []string{"note"}, Mode: logger.PIIModeTruncate, TruncateTo: 100},
	})
	payload := map[string]any{"note": "short"}
	result := logger.SanitizePayload(payload, true, 0)
	if result["note"] != "short" {
		t.Fatalf("short string should not be truncated, got %v", result["note"])
	}
}

func TestPIIHashMode(t *testing.T) {
	defer logger.ResetPIIRules()
	logger.SetPIIRules([]logger.PIIRule{
		{Path: []string{"id"}, Mode: logger.PIIModeHash},
	})
	payload := map[string]any{"id": "user-123"}
	result := logger.SanitizePayload(payload, true, 0)
	s, ok := result["id"].(string)
	if !ok || len(s) != 12 {
		t.Fatalf("id hash = %v", result["id"])
	}
}

func TestPIINestedMap(t *testing.T) {
	payload := map[string]any{
		"user": map[string]any{
			"password": "s3cr3t",
			"name":     "alice",
		},
	}
	result := logger.SanitizePayload(payload, true, 4)
	user, ok := result["user"].(map[string]any)
	if !ok {
		t.Fatalf("user field should be a map, got %T", result["user"])
	}
	if user["password"] == "s3cr3t" { // pragma: allowlist secret
		t.Fatal("nested password should be redacted")
	}
}

func TestPIISliceSanitization(t *testing.T) {
	payload := map[string]any{
		"items": []any{
			map[string]any{"token": "secret-value"}, //nolint // pragma: allowlist secret
			"plain-string",
		},
	}
	result := logger.SanitizePayload(payload, true, 4)
	items, ok := result["items"].([]any)
	if !ok {
		t.Fatalf("items should be []any, got %T", result["items"])
	}
	first, ok := items[0].(map[string]any)
	if !ok {
		t.Fatalf("first item should be map, got %T", items[0])
	}
	if first["token"] == "secret-value" {
		t.Fatal("token in slice should be redacted")
	}
}

func TestPIIClassificationHook(t *testing.T) {
	defer logger.ResetPIIRules()
	logger.SetClassificationHook(func(key string, value any) string {
		if key == "email" {
			return "PII"
		}
		return ""
	})

	payload := map[string]any{"email": "user@example.com", "name": "alice"}
	result := logger.SanitizePayload(payload, true, 0)
	if result["__email__class"] != "PII" {
		t.Fatalf("classification hook should add __email__class, got: %v", result)
	}
}

func TestPIIReceiptHook(t *testing.T) {
	defer logger.ResetPIIRules()
	var receipts []string
	logger.SetReceiptHook(func(path, action string, _ any) {
		receipts = append(receipts, path+":"+action)
	})

	payload := map[string]any{"password": "s3cr3t"}
	logger.SanitizePayload(payload, true, 0)
	if len(receipts) == 0 {
		t.Fatal("receipt hook should have been called")
	}
}

func TestPIIDetectSecretInValue(t *testing.T) {
	// A JWT-like string should be detected and redacted.
	jwt := "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxw" // pragma: allowlist secret
	payload := map[string]any{"data": jwt}
	result := logger.SanitizePayload(payload, true, 0)
	if result["data"] == jwt {
		t.Fatal("JWT-like value should be detected and redacted")
	}
}

func TestPIIShortValueNotRedacted(t *testing.T) {
	payload := map[string]any{"data": "short"}
	result := logger.SanitizePayload(payload, true, 0)
	if result["data"] != "short" {
		t.Fatal("short non-sensitive value should not be redacted")
	}
}

func TestGetPIIRules(t *testing.T) {
	defer logger.ResetPIIRules()
	logger.SetPIIRules([]logger.PIIRule{
		{Path: []string{"x"}, Mode: logger.PIIModeRedact},
	})
	rules := logger.GetPIIRules()
	if len(rules) != 1 {
		t.Fatalf("expected 1 rule, got %d", len(rules))
	}
}

// ---- fingerprint: internal paths ----

func TestComputeErrorFingerprintNoFrames(t *testing.T) {
	fp := logger.ComputeErrorFingerprintFromParts("ValueError", nil)
	if len(fp) != 12 {
		t.Fatalf("fingerprint length = %d", len(fp))
	}
}

// ---- Trace and IsEnabled helpers ----

func TestTrace(t *testing.T) {
	var buf bytes.Buffer
	l := logger.NewBufferLogger(&buf, slog.LevelInfo)
	logger.Trace(l, "trace-message", "key", "val")
	// Trace is below INFO; output will be empty — just verify no panic.
	_ = buf.String()
}

func TestIsEnabled(t *testing.T) {
	var buf bytes.Buffer
	l := logger.NewBufferLogger(&buf, slog.LevelInfo)
	if !logger.IsEnabled(l, slog.LevelInfo) {
		t.Error("expected INFO to be enabled")
	}
	if logger.IsEnabled(l, logger.LevelTrace) {
		t.Error("expected TRACE to be disabled")
	}
}
