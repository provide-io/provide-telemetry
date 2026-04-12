// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// internal_test.go uses package logger (white-box) to reach branches
// that require access to unexported symbols.
package logger

import (
	"context"
	"log/slog"
	"testing"

	"github.com/provide-io/provide-telemetry/go/internal/fingerprintcore"
	"github.com/provide-io/provide-telemetry/go/internal/piicore"
)

// TestGetBoundFieldsBadContextValue covers the !ok branch in GetBoundFields
// where the context value exists but is not map[string]any.
func TestGetBoundFieldsBadContextValue(t *testing.T) {
	// Inject a non-map value directly under the private key.
	ctx := context.WithValue(context.Background(), _contextFieldsKey, "not-a-map")
	fields := GetBoundFields(ctx)
	if len(fields) != 0 {
		t.Fatal("GetBoundFields with bad type should return empty map")
	}
}

// TestConfigurationErrorAsNonMatch covers the false branch in ConfigurationError.As.
func TestConfigurationErrorAsNonMatch(t *testing.T) {
	ce := NewConfigurationError("x")
	var target *ConfigurationError
	// Direct call with a target that is *ConfigurationError, not **TelemetryError.
	got := ce.As(&target)
	if got {
		t.Fatal("As should return false for non-**TelemetryError target")
	}
}

// TestEventSchemaErrorAsNonMatch covers the false branch in EventSchemaError.As.
func TestEventSchemaErrorAsNonMatch(t *testing.T) {
	ese := NewEventSchemaError("y")
	var target *EventSchemaError
	got := ese.As(&target)
	if got {
		t.Fatal("As should return false for non-**TelemetryError target")
	}
}

// TestApplyModeRedact covers the default branch in piicore.ApplyMode (PIIModeRedact).
func TestApplyModeRedact(t *testing.T) {
	val, drop := piicore.ApplyMode("sensitive", piicore.PIIModeRedact, 0)
	if drop {
		t.Fatal("redact mode should not drop the field")
	}
	if val != piicore.Redacted {
		t.Fatalf("redact mode should return %q, got %q", piicore.Redacted, val)
	}
}

// TestApplyContextFieldsWithExistingAttrs covers the r.Attrs copy path
// when the record already has attributes AND bound context fields.
func TestApplyContextFieldsWithExistingAttrs(t *testing.T) {
	cfg := DefaultLogConfig()
	cfg.Level = LogLevelDebug
	Configure(cfg)

	ctx := BindContext(context.Background(), map[string]any{"req_id": "r-1"})
	Logger.InfoContext(ctx, "test.context.attrs", slog.String("key", "value"))
}

// TestApplyStandardFieldsCopiesExistingAttrs covers the r.Attrs copy closure
// inside applyStandardFields when the record already carries attributes.
func TestApplyStandardFieldsCopiesExistingAttrs(t *testing.T) {
	cfg := DefaultLogConfig()
	cfg.ServiceName = "svc"
	Configure(cfg)
	defer func() { Configure(DefaultLogConfig()) }()
	// Log with an attr so the record has existing attrs when standard fields runs.
	Logger.Info("test.std.copy", slog.String("k", "v"))
}

// TestApplyTraceFieldsCopiesExistingAttrs covers the r.Attrs copy closure
// inside applyTraceFields when the record already carries attributes.
func TestApplyTraceFieldsCopiesExistingAttrs(t *testing.T) {
	cfg := DefaultLogConfig()
	Configure(cfg)

	ctx := SetTraceContext(context.Background(), "tid", "sid")
	Logger.InfoContext(ctx, "test.trace.copy", slog.String("k", "v"))
}

// TestExtractFuncNameNoDot covers the branch in fingerprintcore.ExtractFuncName
// where the function name has no "." (no package prefix).
func TestExtractFuncNameNoDot(t *testing.T) {
	result := fingerprintcore.ExtractFuncName("nodotfunction")
	if result != "nodotfunction" {
		t.Fatalf("ExtractFuncName without dot = %q, want 'nodotfunction'", result)
	}
}

// TestComputeErrorFingerprintEmptyFrame covers the frame.Function=="" && !more branch
// by passing a zero-valued PC that resolves to an empty frame.
func TestComputeErrorFingerprintEmptyFrame(t *testing.T) {
	// Pass a slice with a zero PC value; CallersFrames returns a frame where
	// Function == "" and more == false, triggering the guarded break.
	pcs := []uintptr{0}
	fp := _computeErrorFingerprint("ValueError", pcs)
	if len(fp) != 12 {
		t.Fatalf("fingerprint with empty frame length = %d", len(fp))
	}
}

// TestGetLoggerJSON covers the JSON format branch in GetLogger.
func TestGetLoggerJSON(t *testing.T) {
	cfg := DefaultLogConfig()
	cfg.Format = LogFormatJSON
	Configure(cfg)
	defer func() { Configure(DefaultLogConfig()) }()

	l := GetLogger(context.Background(), "test")
	if l == nil {
		t.Fatal("GetLogger with JSON format should return non-nil")
	}
}
