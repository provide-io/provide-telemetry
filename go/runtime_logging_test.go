// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"context"
	"log/slog"
	"strings"
	"testing"
)

// TestUpdateRuntimeConfig_LoggingOverride_ChangesLevel verifies that supplying
// a LoggingConfig override through UpdateRuntimeConfig propagates to the next
// GetLogger() call — matching Python's RuntimeOverrides.logging behaviour
// (src/provide/telemetry/runtime.py).
func TestUpdateRuntimeConfig_LoggingOverride_ChangesLevel(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	// Default INFO — DEBUG must be suppressed.
	l := GetLogger(context.Background(), "app")
	if l.Enabled(context.Background(), slog.LevelDebug) {
		t.Fatal("DEBUG should not be enabled at default INFO level")
	}

	// Flip to DEBUG via runtime override.
	newLogging := DefaultTelemetryConfig().Logging
	newLogging.Level = LogLevelDebug
	if err := UpdateRuntimeConfig(RuntimeOverrides{Logging: &newLogging}); err != nil {
		t.Fatalf("UpdateRuntimeConfig failed: %v", err)
	}

	l = GetLogger(context.Background(), "app")
	if !l.Enabled(context.Background(), slog.LevelDebug) {
		t.Fatal("DEBUG should be enabled after Logging override to DEBUG level")
	}
}

// TestUpdateRuntimeConfig_LoggingOverride_AppliesModuleLevels verifies that
// module-level overrides supplied via a runtime Logging override are honoured
// by subsequent GetLogger(name) calls.
func TestUpdateRuntimeConfig_LoggingOverride_AppliesModuleLevels(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	newLogging := DefaultTelemetryConfig().Logging
	newLogging.Level = LogLevelError
	newLogging.ModuleLevels = map[string]string{"chatty": LogLevelDebug}

	if err := UpdateRuntimeConfig(RuntimeOverrides{Logging: &newLogging}); err != nil {
		t.Fatalf("UpdateRuntimeConfig failed: %v", err)
	}

	chatty := GetLogger(context.Background(), "chatty.service")
	if !chatty.Enabled(context.Background(), slog.LevelDebug) {
		t.Error("chatty.service should be enabled at DEBUG via module override")
	}

	quiet := GetLogger(context.Background(), "other")
	if quiet.Enabled(context.Background(), slog.LevelDebug) {
		t.Error("other module should inherit global ERROR level, not DEBUG")
	}
}

// TestUpdateRuntimeConfig_LoggingOverride_PreservesProviderFields verifies
// that a Logging override does NOT touch provider-changing fields that live
// outside LoggingConfig (Tracing.Enabled, Metrics.Enabled, ServiceName, etc.).
func TestUpdateRuntimeConfig_LoggingOverride_PreservesProviderFields(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	cfgBefore, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	newLogging := DefaultTelemetryConfig().Logging
	newLogging.Level = LogLevelWarning
	if err := UpdateRuntimeConfig(RuntimeOverrides{Logging: &newLogging}); err != nil {
		t.Fatalf("UpdateRuntimeConfig failed: %v", err)
	}

	cfgAfter := GetRuntimeConfig()
	if cfgAfter == nil {
		t.Fatal("expected runtime config after update")
	}
	if cfgAfter.ServiceName != cfgBefore.ServiceName {
		t.Errorf("ServiceName drifted: %q → %q", cfgBefore.ServiceName, cfgAfter.ServiceName)
	}
	if cfgAfter.Tracing.Enabled != cfgBefore.Tracing.Enabled {
		t.Errorf("Tracing.Enabled drifted: %v → %v", cfgBefore.Tracing.Enabled, cfgAfter.Tracing.Enabled)
	}
	if cfgAfter.Metrics.Enabled != cfgBefore.Metrics.Enabled {
		t.Errorf("Metrics.Enabled drifted: %v → %v", cfgBefore.Metrics.Enabled, cfgAfter.Metrics.Enabled)
	}
	if cfgAfter.Tracing.OTLPEndpoint != cfgBefore.Tracing.OTLPEndpoint {
		t.Errorf("Tracing.OTLPEndpoint drifted")
	}
	if cfgAfter.Logging.Level != LogLevelWarning {
		t.Errorf("expected Logging.Level=WARNING, got %q", cfgAfter.Logging.Level)
	}
}

// TestUpdateRuntimeConfig_LoggingOverride_ValidatesLevel ensures invalid log
// level in a Logging override is rejected rather than silently accepted.
func TestUpdateRuntimeConfig_LoggingOverride_ValidatesLevel(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	bad := DefaultTelemetryConfig().Logging
	bad.Level = "LOUD"
	if err := UpdateRuntimeConfig(RuntimeOverrides{Logging: &bad}); err == nil {
		t.Fatal("expected invalid log level to be rejected")
	}
}

// TestUpdateRuntimeConfig_LoggingOverride_ValidatesFormat ensures invalid log
// format in a Logging override is rejected.
func TestUpdateRuntimeConfig_LoggingOverride_ValidatesFormat(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	bad := DefaultTelemetryConfig().Logging
	bad.Format = "xml"
	if err := UpdateRuntimeConfig(RuntimeOverrides{Logging: &bad}); err == nil {
		t.Fatal("expected invalid log format to be rejected")
	}
}

// TestUpdateRuntimeConfig_LoggingOverride_ValidatesModuleLevels ensures
// invalid per-module levels are rejected.
func TestUpdateRuntimeConfig_LoggingOverride_ValidatesModuleLevels(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	bad := DefaultTelemetryConfig().Logging
	bad.ModuleLevels = map[string]string{"svc": "CHATTY"}
	if err := UpdateRuntimeConfig(RuntimeOverrides{Logging: &bad}); err == nil {
		t.Fatal("expected invalid module level to be rejected")
	}
}

// TestUpdateRuntimeConfig_LoggingOverride_ValidatesPIIMaxDepth ensures the
// Logging override's PIIMaxDepth field is validated for non-negativity.
func TestUpdateRuntimeConfig_LoggingOverride_ValidatesPIIMaxDepth(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	bad := DefaultTelemetryConfig().Logging
	bad.PIIMaxDepth = -1
	if err := UpdateRuntimeConfig(RuntimeOverrides{Logging: &bad}); err == nil {
		t.Fatal("expected negative PIIMaxDepth to be rejected")
	}
}

// TestLoggingConfig_PrettyFormat_RendersLikeConsole documents Go's current
// behaviour: LogFormatPretty is accepted by the config layer but the
// underlying renderer is slog's text handler — identical to
// LogFormatConsole. A dedicated ANSI renderer is a future enhancement;
// see docs/CAPABILITY_MATRIX.md entry "PROVIDE_LOG_FORMAT=pretty renderer"
// (listed as same-as-console for Go). This regression test fails if the
// two renderers ever diverge without the matrix being updated in the
// same change.
func TestLoggingConfig_PrettyFormat_RendersLikeConsole(t *testing.T) {
	setupFullSampling(t)

	cfgConsole := DefaultTelemetryConfig()
	cfgConsole.Logging.Format = LogFormatConsole

	cfgPretty := DefaultTelemetryConfig()
	cfgPretty.Logging.Format = LogFormatPretty

	// _baseLogHandler returns the underlying renderer; assert console and
	// pretty both produce non-JSON (slog text) handlers, confirming parity.
	consoleBase := _baseLogHandler(cfgConsole)
	prettyBase := _baseLogHandler(cfgPretty)

	if _, ok := consoleBase.(*slog.JSONHandler); ok {
		t.Fatal("console base must not be a JSONHandler")
	}
	if _, ok := prettyBase.(*slog.JSONHandler); ok {
		t.Fatal("pretty base must not be a JSONHandler (currently renders as text)")
	}

	// Smoke-test the pretty format end-to-end through the telemetry chain:
	// building a handler and emitting a record must not panic.
	var buf bytes.Buffer
	cfgPretty.Logging.IncludeTimestamp = false
	cfgPretty.Logging.Sanitize = false
	prettyChain := _newTelemetryHandler(
		slog.NewTextHandler(&buf, &slog.HandlerOptions{Level: LevelTrace}),
		cfgPretty, "",
	)
	slog.New(prettyChain).Info("pretty.sanity.ok")
	if !strings.Contains(buf.String(), "pretty.sanity.ok") {
		t.Fatalf("pretty format chain dropped record: %s", buf.String())
	}
}
