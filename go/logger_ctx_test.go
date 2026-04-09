// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"context"
	"os"
	"strings"
	"testing"
)

// captureGetLogger redirects os.Stderr so that GetLogger's internally created
// text handler writes to a buffer. Returns the captured output of fn().
func captureGetLogger(t *testing.T, fn func()) string {
	t.Helper()
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("os.Pipe: %v", err)
	}
	origStderr := os.Stderr
	os.Stderr = w
	t.Cleanup(func() { os.Stderr = origStderr })

	fn()

	_ = w.Close()
	os.Stderr = origStderr

	var buf bytes.Buffer
	_, _ = buf.ReadFrom(r)
	return buf.String()
}

// ── GetLogger context extraction tests ───────────────────────────────────────

func TestGetLogger_PreAttachesTraceAndSpanFromContext(t *testing.T) {
	resetSetupState(t)
	setupFullSampling(t)
	t.Cleanup(func() { resetSetupState(t) })

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false
	_configureLogger(cfg)
	t.Cleanup(func() { _configureLogger(DefaultTelemetryConfig()) })

	ctx := context.Background()
	ctx = SetTraceContext(ctx, "aabbccddeeff0011aabbccddeeff0011", "1122334455667788")

	out := captureGetLogger(t, func() {
		logger := GetLogger(ctx, "svc.test")
		logger.Info("test-event") // no ctx — relies on pre-attached attrs
	})

	if !strings.Contains(out, "aabbccddeeff0011aabbccddeeff0011") {
		t.Errorf("expected trace.id in output, got: %q", out)
	}
	if !strings.Contains(out, "1122334455667788") {
		t.Errorf("expected span.id in output, got: %q", out)
	}
}

func TestGetLogger_EmptyContextNoTraceAttached(t *testing.T) {
	resetSetupState(t)
	setupFullSampling(t)
	t.Cleanup(func() { resetSetupState(t) })

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false
	_configureLogger(cfg)
	t.Cleanup(func() { _configureLogger(DefaultTelemetryConfig()) })

	out := captureGetLogger(t, func() {
		logger := GetLogger(context.Background(), "svc.test")
		logger.Info("test-event")
	})

	if strings.Contains(out, "trace.id") {
		t.Errorf("unexpected trace.id in output for empty context, got: %q", out)
	}
	if strings.Contains(out, "span.id") {
		t.Errorf("unexpected span.id in output for empty context, got: %q", out)
	}
}

func TestGetLogger_TraceIDOnlyAttachedWhenSpanIDEmpty(t *testing.T) {
	resetSetupState(t)
	setupFullSampling(t)
	t.Cleanup(func() { resetSetupState(t) })

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false
	_configureLogger(cfg)
	t.Cleanup(func() { _configureLogger(DefaultTelemetryConfig()) })

	ctx := context.Background()
	ctx = SetTraceContext(ctx, "aabbccddeeff0011aabbccddeeff0011", "") // span empty

	out := captureGetLogger(t, func() {
		logger := GetLogger(ctx, "svc.test")
		logger.Info("test-event")
	})

	if !strings.Contains(out, "aabbccddeeff0011aabbccddeeff0011") {
		t.Errorf("expected trace.id in output, got: %q", out)
	}
	if strings.Contains(out, "span.id") {
		t.Errorf("unexpected span.id when span is empty, got: %q", out)
	}
}

func TestGetLogger_SpanIDOnlyAttachedWhenTraceIDEmpty(t *testing.T) {
	resetSetupState(t)
	setupFullSampling(t)
	t.Cleanup(func() { resetSetupState(t) })

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false
	_configureLogger(cfg)
	t.Cleanup(func() { _configureLogger(DefaultTelemetryConfig()) })

	ctx := context.Background()
	ctx = SetTraceContext(ctx, "", "1122334455667788") // trace empty

	out := captureGetLogger(t, func() {
		logger := GetLogger(ctx, "svc.test")
		logger.Info("test-event")
	})

	if strings.Contains(out, "trace.id") {
		t.Errorf("unexpected trace.id when trace is empty, got: %q", out)
	}
	if !strings.Contains(out, "1122334455667788") {
		t.Errorf("expected span.id in output, got: %q", out)
	}
}
