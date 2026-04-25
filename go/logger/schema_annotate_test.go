// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package logger

import (
	"bytes"
	"context"
	"log/slog"
	"strings"
	"testing"
	"time"
)

// TestHandlerSchemaAnnotatesEventNameViolation verifies that strict-schema
// validation failures on the event name annotate the emitted record with
// _schema_error rather than silently dropping it. This matches the parent
// telemetry package (see go/logger.go:applySchema call-site) and the
// cross-language contract documented in docs/CAPABILITY_MATRIX.md:
// "Strict-schema rejection emits _schema_error instead of dropping the
// record".
func TestHandlerSchemaAnnotatesEventNameViolation(t *testing.T) {
	buf := &bytes.Buffer{}
	base := slog.NewJSONHandler(buf, &slog.HandlerOptions{Level: LevelTrace})
	cfg := DefaultLogConfig()
	cfg.StrictSchema = true
	h := _newTelemetryHandler(base, cfg, "test")

	// "too.short" is a 2-segment event name; ValidateEventName requires
	// 3 or more segments when strict.
	r := slog.NewRecord(time.Now(), slog.LevelInfo, "too.short", 0)
	if err := h.Handle(context.Background(), r); err != nil {
		t.Fatalf("Handle returned error: %v", err)
	}

	out := buf.String()
	if out == "" {
		t.Fatal("schema-invalid record should be annotated and emitted, not dropped")
	}
	if !strings.Contains(out, "_schema_error") {
		t.Fatalf("expected _schema_error annotation on emitted record, got: %s", out)
	}
}

// TestHandlerSchemaAnnotatesRequiredKeyViolation verifies that missing
// required keys annotate the emitted record with _schema_error rather than
// dropping it.
func TestHandlerSchemaAnnotatesRequiredKeyViolation(t *testing.T) {
	buf := &bytes.Buffer{}
	base := slog.NewJSONHandler(buf, &slog.HandlerOptions{Level: LevelTrace})
	cfg := DefaultLogConfig()
	cfg.StrictSchema = true
	cfg.RequiredKeys = []string{"request_id"}
	h := _newTelemetryHandler(base, cfg, "test")

	r := slog.NewRecord(time.Now(), slog.LevelInfo, "a.b.c", 0)
	// No request_id attribute → validation fails → record is annotated.
	if err := h.Handle(context.Background(), r); err != nil {
		t.Fatalf("Handle returned error: %v", err)
	}

	out := buf.String()
	if out == "" {
		t.Fatal("required-key-missing record should be annotated and emitted, not dropped")
	}
	if !strings.Contains(out, "_schema_error") {
		t.Fatalf("expected _schema_error annotation, got: %s", out)
	}
}

// TestHandlerSchemaValidRecord_NoAnnotation verifies the happy path: a
// schema-valid record is emitted without any _schema_error annotation.
func TestHandlerSchemaValidRecord_NoAnnotation(t *testing.T) {
	buf := &bytes.Buffer{}
	base := slog.NewJSONHandler(buf, &slog.HandlerOptions{Level: LevelTrace})
	cfg := DefaultLogConfig()
	cfg.StrictSchema = true
	cfg.RequiredKeys = []string{"request_id"}
	h := _newTelemetryHandler(base, cfg, "test")

	r := slog.NewRecord(time.Now(), slog.LevelInfo, "a.b.c", 0)
	r.AddAttrs(slog.String("request_id", "req-1"))
	if err := h.Handle(context.Background(), r); err != nil {
		t.Fatalf("Handle returned error: %v", err)
	}

	out := buf.String()
	if out == "" {
		t.Fatal("valid record should be emitted")
	}
	if strings.Contains(out, "_schema_error") {
		t.Fatalf("did not expect _schema_error annotation on valid record, got: %s", out)
	}
}
