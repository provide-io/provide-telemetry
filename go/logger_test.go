// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"context"
	"log/slog"
	"os"
	"strings"
	"testing"
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
	if _, err := SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 1.0}); err != nil {
		t.Fatal(err)
	}
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
	if _, err := SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 0.0}); err != nil {
		t.Fatal(err)
	}
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

func TestGetLogger_InvalidEnvFallsBackToDefaultConfig(t *testing.T) {
	orig := Logger
	Logger = nil
	t.Cleanup(func() { Logger = orig })
	t.Setenv("PROVIDE_LOG_INCLUDE_TIMESTAMP", "not-a-bool")

	l := GetLogger(context.Background(), "fallback.invalid-env")
	if l == nil {
		t.Fatal("GetLogger returned nil when ConfigFromEnv failed")
	}
}

func TestTelemetryConfigFromHandler_FindsNestedTelemetryHandler(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	handler := newMultiHandler(slog.NewTextHandler(os.Stderr, nil), _newTelemetryHandler(slog.NewTextHandler(os.Stderr, nil), cfg, "nested"))

	got, ok := _telemetryConfigFromHandler(handler)
	if !ok {
		t.Fatal("expected to find telemetry config inside multiHandler")
	}
	if got != cfg {
		t.Fatalf("expected original config pointer, got %+v", got)
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

func TestGetTraceSpanFromContext_ReturnsEmpty(t *testing.T) {
	traceID, spanID := _getTraceSpanFromContext(context.Background())
	if traceID != "" || spanID != "" {
		t.Errorf("expected empty trace/span IDs, got %q %q", traceID, spanID)
	}
}
