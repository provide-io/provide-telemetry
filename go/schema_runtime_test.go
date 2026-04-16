// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"log/slog"
	"strings"
	"testing"
)

func TestHandler_RequiredKeys_AnnotatesWithoutStrictSchema(t *testing.T) {
	_strictSchema = false
	t.Cleanup(func() { _strictSchema = false })
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.EventSchema.RequiredKeys = []string{"request_id"}
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("user.auth.login")

	if buf.Len() == 0 {
		t.Fatal("missing required key should annotate and emit, not drop")
	}
	if !strings.Contains(buf.String(), "_schema_error") {
		t.Fatalf("expected _schema_error annotation, got: %s", buf.String())
	}
}

func TestHandler_RequiredKeys_PassWithoutStrictSchema(t *testing.T) {
	_strictSchema = false
	t.Cleanup(func() { _strictSchema = false })
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.EventSchema.RequiredKeys = []string{"request_id"}
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("user.auth.login", slog.String("request_id", "req-123"))

	if buf.Len() == 0 {
		t.Fatal("expected record to pass when required key is present")
	}
	if strings.Contains(buf.String(), "_schema_error") {
		t.Fatalf("did not expect _schema_error annotation, got: %s", buf.String())
	}
}
