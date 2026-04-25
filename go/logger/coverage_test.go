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

	// Missing required key → record is annotated with _schema_error and
	// still emitted (cross-language contract).
	logger.Logger.Info("test.schema.check")
	// With required key → record passes cleanly (no annotation).
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
