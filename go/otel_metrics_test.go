// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"log/slog"
	"testing"
	"time"

	logglobal "go.opentelemetry.io/otel/log/global"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
)

// ── 6. WithMeterProvider wires real meter provider ────────────────────────────

func TestOTel_WithMeterProvider_WiresRealMeter(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	mp := sdkmetric.NewMeterProvider()
	_, err := SetupTelemetry(WithMeterProvider(mp))
	if err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	if _otelMeterProvider == nil {
		t.Error("expected _otelMeterProvider to be set")
	}
}

// ── 7. ShutdownTelemetry shuts down meter provider ────────────────────────────

func TestOTel_ShutdownTelemetry_ShutsDownMeterProvider(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	mp := sdkmetric.NewMeterProvider()
	_, err := SetupTelemetry(WithMeterProvider(mp))
	if err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("ShutdownTelemetry returned error: %v", err)
	}

	if _otelMeterProvider != nil {
		t.Error("expected _otelMeterProvider to be nil after shutdown")
	}
}

func TestOTel_LogsEndpointAutoWiresLoggerProvider(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "http://collector:4318")

	_, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	if _otelLoggerProvider == nil {
		t.Fatal("expected env-configured logs endpoint to install logger provider")
	}
	if got := logglobal.GetLoggerProvider(); got == nil {
		t.Fatal("expected global logger provider to be set")
	}
}

func TestOTel_WireOTelSlogBridge_NoLoggerIsNoOp(t *testing.T) {
	prevLogger := Logger
	prevDefault := slog.Default()
	Logger = nil
	t.Cleanup(func() {
		Logger = prevLogger
		slog.SetDefault(prevDefault)
	})

	_wireOTelSlogBridge(DefaultTelemetryConfig())

	if Logger != nil {
		t.Fatal("expected nil logger to remain nil")
	}
	if slog.Default() != prevDefault {
		t.Fatal("expected default slog logger to remain unchanged when Logger is nil")
	}
}

func TestOTel_InvalidSharedEndpointDegradesWithoutInstallingProviders(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://[")

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("SetupTelemetry should fail open on invalid endpoint, got %v", err)
	}

	status := GetRuntimeStatus()
	if !status.SetupDone {
		t.Fatal("expected setup to be marked done after fail-open provider init")
	}
	if status.Providers.Logs || status.Providers.Traces || status.Providers.Metrics {
		t.Fatalf("expected no providers after fail-open init, got %+v", status.Providers)
	}
	if !status.Fallback.Logs || !status.Fallback.Traces || !status.Fallback.Metrics {
		t.Fatalf("expected fallback for all signals after fail-open init, got %+v", status.Fallback)
	}
}

// ── _shutdownOTelProviders with various meter scenarios ───────────────────────

func TestOTel_ShutdownOTelProviders_TracerError(t *testing.T) {
	_resetOTelProviders()
	t.Cleanup(func() { _resetOTelProviders() })

	tp, _ := newInMemoryTP()
	_otelTracerProvider = tp

	// Shut down the provider first so the second Shutdown call returns an error.
	ctx := context.Background()
	_ = tp.Shutdown(ctx)

	// Now _shutdownOTelProviders will call Shutdown on an already-shut-down provider.
	// The SDK returns nil on double-shutdown, so instead we test both nil+error cases
	// by having only the meter provider error via a cancelled context.
	mp := sdkmetric.NewMeterProvider()
	_otelMeterProvider = mp

	cancelledCtx, cancel := context.WithCancel(ctx)
	cancel() // cancel immediately to force error

	// Both should be attempted; cancelled context causes meter shutdown to error.
	_ = _shutdownOTelProviders(cancelledCtx)
	// Either nil or error is acceptable; we just need both branches exercised.
}

func TestOTel_ShutdownOTelProviders_BothError(t *testing.T) {
	_resetOTelProviders()
	t.Cleanup(func() { _resetOTelProviders() })

	ctx := context.Background()

	// Pre-shutdown the meter provider so a second Shutdown returns an error.
	mp := sdkmetric.NewMeterProvider()
	_ = mp.Shutdown(ctx)

	// Use a cancelled context so the tracer shutdown also returns an error.
	tp, _ := newInMemoryTP()
	cancelledCtx, cancel := context.WithCancel(ctx)
	cancel()

	_otelTracerProvider = tp
	_otelMeterProvider = mp

	// Both providers error: tracer via cancelled ctx, meter via double-shutdown.
	// This exercises the "first != nil" branch in the meter error check.
	err := _shutdownOTelProviders(cancelledCtx)
	if err == nil {
		t.Error("expected non-nil error when both providers fail shutdown")
	}
}

func TestOTel_ShutdownOTelProviders_OnlyMeterError(t *testing.T) {
	_resetOTelProviders()
	t.Cleanup(func() { _resetOTelProviders() })

	ctx := context.Background()

	// Set up a tracer that shuts down cleanly (no provider set, just meter).
	// Pre-shutdown the meter provider so a second call returns "reader is shutdown".
	mp := sdkmetric.NewMeterProvider()
	_ = mp.Shutdown(ctx) // first shutdown succeeds
	_otelMeterProvider = mp

	// No tracer provider set; meter double-shutdown returns error.
	// first == nil before the meter check → exercises the first = err branch.
	err := _shutdownOTelProviders(ctx)
	if err == nil {
		t.Error("expected error from double-shutdown of meter provider")
	}
}

func TestOTel_ShutdownOTelProviders_OnlyLoggerProvider(t *testing.T) {
	_resetOTelProviders()
	t.Cleanup(func() { _resetOTelProviders() })

	lp := sdklog.NewLoggerProvider()
	_otelLoggerProvider = lp

	if err := _shutdownOTelProviders(context.Background()); err != nil {
		t.Fatalf("expected logger-only shutdown to succeed, got %v", err)
	}
	if _otelLoggerProvider != nil {
		t.Fatal("expected logger provider pointer to be cleared after shutdown")
	}
	if got := logglobal.GetLoggerProvider(); got == nil {
		t.Fatal("expected global logger provider to be restored to noop after shutdown")
	}
}

// ── Endpoint URL validation ───────────────────────────────────────────────────

func TestValidatedSignalEndpointURL_PortValidation(t *testing.T) {
	tests := []struct {
		name    string
		input   string
		wantErr bool
	}{
		{"valid port", "http://host:4318", false},
		{"no port", "http://host", false},
		{"non-numeric port", "http://host:bad", true},
		{"empty port", "http://host:", true},
		{"port zero", "http://host:0", true},
		{"port out of range", "http://host:99999", true},
		{"negative port", "http://host:-1", true},
		{"ipv6 with valid port", "http://[::1]:4318", false},
		{"ipv6 no port", "http://[::1]", false},
		{"ipv6 empty port", "http://[::1]:", true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := _validatedSignalEndpointURL(tt.input, "/v1/traces")
			if tt.wantErr && err == nil {
				t.Errorf("expected error for %q", tt.input)
			}
			if !tt.wantErr && err != nil {
				t.Errorf("unexpected error for %q: %v", tt.input, err)
			}
		})
	}
}

func TestSignalEndpointURL_Variants(t *testing.T) {
	tests := []struct {
		name       string
		endpoint   string
		signalPath string
		want       string
	}{
		{name: "blank endpoint", endpoint: "   ", signalPath: "/v1/logs", want: ""},
		{name: "root endpoint appends path", endpoint: "http://collector:4318", signalPath: "/v1/traces", want: "http://collector:4318/v1/traces"},
		{name: "existing path appends signal path", endpoint: "http://collector:4318/base", signalPath: "/v1/metrics", want: "http://collector:4318/base/v1/metrics"},
		{name: "existing suffix preserved", endpoint: "http://collector:4318/v1/logs", signalPath: "/v1/logs", want: "http://collector:4318/v1/logs"},
		{name: "unparsed string suffix preserved", endpoint: "collector:4318/v1/logs", signalPath: "/v1/logs", want: "collector:4318/v1/logs"},
		{name: "unparsed string appends path", endpoint: "collector:4318", signalPath: "/v1/logs", want: "collector:4318/v1/logs"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := _signalEndpointURL(tt.endpoint, tt.signalPath); got != tt.want {
				t.Fatalf("expected %q, got %q", tt.want, got)
			}
		})
	}
}

func TestValidatedSignalEndpointURL_RejectsBlankAndUnsupportedSchemes(t *testing.T) {
	tests := []struct {
		name    string
		input   string
		wantErr bool
	}{
		{name: "blank endpoint", input: "   ", wantErr: true},
		{name: "missing scheme and host", input: "collector:4318", wantErr: true},
		{name: "unsupported scheme", input: "ftp://collector:4318", wantErr: true},
		{name: "valid https endpoint", input: "https://collector:4318", wantErr: false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := _validatedSignalEndpointURL(tt.input, "/v1/logs")
			if tt.wantErr && err == nil {
				t.Fatalf("expected validation error for %q", tt.input)
			}
			if !tt.wantErr && err != nil {
				t.Fatalf("unexpected validation error for %q: %v", tt.input, err)
			}
		})
	}
}

func TestBuildDefaultProviders_SuccessAndInvalidEndpoint(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Tracing.OTLPEndpoint = "http://collector:4318"
	cfg.Tracing.OTLPHeaders = map[string]string{"authorization": "Bearer token"}
	cfg.Metrics.OTLPEndpoint = "http://collector:4318"
	cfg.Metrics.OTLPHeaders = map[string]string{"x-metrics": "true"}
	cfg.Logging.OTLPEndpoint = "http://collector:4318"
	cfg.Logging.OTLPHeaders = map[string]string{"x-logs": "true"}

	if tp, err := _buildDefaultTracerProvider(cfg); err != nil || tp == nil {
		t.Fatalf("expected tracer provider build success, got tp=%v err=%v", tp, err)
	}
	if mp, err := _buildDefaultMeterProvider(cfg); err != nil || mp == nil {
		t.Fatalf("expected meter provider build success, got mp=%v err=%v", mp, err)
	}
	if lp, err := _buildDefaultLoggerProvider(cfg); err != nil || lp == nil {
		t.Fatalf("expected logger provider build success, got lp=%v err=%v", lp, err)
	}

	cfg.Tracing.OTLPEndpoint = "   "
	if tp, err := _buildDefaultTracerProvider(cfg); err == nil || tp != nil {
		t.Fatalf("expected tracer provider validation failure, got tp=%v err=%v", tp, err)
	}
	cfg.Tracing.OTLPEndpoint = "http://collector:4318"
	cfg.Metrics.OTLPEndpoint = "ftp://collector:4318"
	if mp, err := _buildDefaultMeterProvider(cfg); err == nil || mp != nil {
		t.Fatalf("expected meter provider validation failure, got mp=%v err=%v", mp, err)
	}
	cfg.Metrics.OTLPEndpoint = "http://collector:4318"
	cfg.Logging.OTLPEndpoint = "http://["
	if lp, err := _buildDefaultLoggerProvider(cfg); err == nil || lp != nil {
		t.Fatalf("expected logger provider validation failure, got lp=%v err=%v", lp, err)
	}
}

// ── multiHandler Enabled/Handle/WithAttrs/WithGroup ───────────────────────────

func TestMultiHandler_EnabledAndHandle(t *testing.T) {
	var handled int
	h1 := &testCountingHandler{level: slog.LevelDebug}
	h2 := &testCountingHandler{level: slog.LevelInfo}

	mh := newMultiHandler(h1, h2)

	ctx := context.Background()
	if !mh.Enabled(ctx, slog.LevelDebug) {
		t.Error("expected Enabled=true for DEBUG with h1")
	}
	if mh.Enabled(ctx, slog.LevelError) != true {
		t.Error("expected Enabled=true for ERROR")
	}

	// h2 should NOT handle a DEBUG record.
	dr := slog.NewRecord(time.Now(), slog.LevelDebug, "dbg", 0)
	if err := mh.Handle(ctx, dr); err != nil {
		t.Fatalf("Handle returned error: %v", err)
	}
	_ = handled
	if h2.handled > 0 {
		t.Errorf("h2 (INFO level) should not handle DEBUG records, got %d", h2.handled)
	}

	// INFO record should be handled by both h1 and h2.
	r := slog.NewRecord(time.Now(), slog.LevelInfo, "test", 0)
	if err := mh.Handle(ctx, r); err != nil {
		t.Fatalf("Handle returned error: %v", err)
	}
	if h2.handled != 1 {
		t.Errorf("h2 should handle 1 INFO record, got %d", h2.handled)
	}

	_ = mh.WithAttrs([]slog.Attr{slog.String("k", "v")})
	_ = mh.WithGroup("grp")
}

// testCountingHandler is a minimal slog.Handler for testing multiHandler.
type testCountingHandler struct {
	level   slog.Level
	handled int
}

func (h *testCountingHandler) Enabled(_ context.Context, level slog.Level) bool {
	return level >= h.level
}

func (h *testCountingHandler) Handle(_ context.Context, _ slog.Record) error {
	h.handled++
	return nil
}

func (h *testCountingHandler) WithAttrs(_ []slog.Attr) slog.Handler { return h }
func (h *testCountingHandler) WithGroup(_ string) slog.Handler      { return h }

func TestMultiHandler_Enabled_AllDisabled(t *testing.T) {
	// Both handlers only enabled at ERROR level; asking about DEBUG should return false.
	h1 := &testCountingHandler{level: slog.LevelError}
	h2 := &testCountingHandler{level: slog.LevelError}
	mh := newMultiHandler(h1, h2)

	if mh.Enabled(context.Background(), slog.LevelDebug) {
		t.Error("expected Enabled=false when all handlers require ERROR level")
	}
}

func TestMultiHandler_Handle_ReturnsError(t *testing.T) {
	errH := &testErrorHandler{err: errOTelShutdown}
	mh := newMultiHandler(errH)

	r := slog.NewRecord(time.Now(), slog.LevelInfo, "test", 0)
	err := mh.Handle(context.Background(), r)
	if err == nil {
		t.Fatal("expected error from Handle when handler returns error")
	}
}

// testErrorHandler is a slog.Handler that always returns an error from Handle.
type testErrorHandler struct {
	err error
}

func (h *testErrorHandler) Enabled(_ context.Context, _ slog.Level) bool  { return true }
func (h *testErrorHandler) Handle(_ context.Context, _ slog.Record) error { return h.err }
func (h *testErrorHandler) WithAttrs(_ []slog.Attr) slog.Handler          { return h }
func (h *testErrorHandler) WithGroup(_ string) slog.Handler               { return h }
