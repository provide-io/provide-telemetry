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
)

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

// TestHandler_PIISanitization_MessageContent regression-tests the fix for the
// secret-in-message leak. Before the fix, applyPII sanitized only attributes
// and rebuilt the slog.Record with r.Message unchanged — secrets embedded in
// the message string itself (e.g. log.Info("token AKIA...")) leaked verbatim.
func TestHandler_PIISanitization_MessageContent(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = true

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	// AWS access key ID — matches a built-in secret pattern.
	l.Info("token AKIAIOSFODNN7EXAMPLE leaked") // pragma: allowlist secret

	out := buf.String()
	if strings.Contains(out, "AKIAIOSFODNN7EXAMPLE") { // pragma: allowlist secret
		t.Errorf("secret leaked verbatim in message: %s", out)
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

// ── Schema strict tests ───────────────────────────────────────────────────────

func TestHandler_SchemaStrict_Annotates(t *testing.T) {
	_strictSchema = true
	t.Cleanup(func() { _strictSchema = false })
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	// Not a valid dotted event name (fails segment-count validation).
	// Event is annotated with _schema_error instead of dropped —
	// cross-language standard: never lose telemetry on schema violation.
	l.Info("invalid")

	if buf.Len() == 0 {
		t.Fatal("schema violation should annotate and emit, not drop")
	}
	if !strings.Contains(buf.String(), "_schema_error") {
		t.Errorf("expected _schema_error annotation, got: %s", buf.String())
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

func TestHandler_SchemaStrict_RequiredKeys_Annotates(t *testing.T) {
	_strictSchema = true
	t.Cleanup(func() { _strictSchema = false })
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.EventSchema.RequiredKeys = []string{"domain"}
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("user.auth.login")

	if buf.Len() == 0 {
		t.Fatal("schema violation should annotate and emit, not drop")
	}
	if !strings.Contains(buf.String(), "_schema_error") {
		t.Errorf("expected _schema_error annotation, got: %s", buf.String())
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

// ── JSON output tests ─────────────────────────────────────────────────────────

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

// ── _configureLogger produces JSON output when format=json ───────────────────

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

func TestConfigureLogger_JSONFormat_OmitsTimestampWhenDisabled(t *testing.T) {
	setupFullSampling(t)

	r, w, _ := os.Pipe()
	origStderr := os.Stderr
	os.Stderr = w
	defer func() { os.Stderr = origStderr }()

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Format = LogFormatJSON
	cfg.Logging.IncludeTimestamp = false
	cfg.Logging.Sanitize = false
	_configureLogger(cfg)
	t.Cleanup(func() { _configureLogger(DefaultTelemetryConfig()) })

	Logger.Info("no timestamp please")
	_ = w.Close()

	var buf bytes.Buffer
	_, _ = buf.ReadFrom(r)

	var m map[string]any
	if err := json.Unmarshal(buf.Bytes(), &m); err != nil {
		t.Fatalf("expected JSON output, got %v", err)
	}
	if _, ok := m[slog.TimeKey]; ok {
		t.Fatalf("expected %q to be omitted when timestamps are disabled, got %v", slog.TimeKey, m)
	}
	if _, ok := m["message"]; !ok {
		t.Fatalf("expected message key to be renamed, got %v", m)
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
