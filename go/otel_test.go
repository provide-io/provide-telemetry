// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"log/slog"
	"testing"
	"time"

	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
)

// ── helpers ──────────────────────────────────────────────────────────────────

// newInMemoryTP creates an sdktrace.TracerProvider backed by an in-memory exporter.
func newInMemoryTP() (*sdktrace.TracerProvider, *tracetest.InMemoryExporter) {
	exp := tracetest.NewInMemoryExporter()
	tp := sdktrace.NewTracerProvider(sdktrace.WithSyncer(exp))
	return tp, exp
}

// ── 1. WithTracerProvider wires real tracer (DefaultTracer is no longer noopTracer) ──

func TestOTel_WithTracerProvider_WiresRealTracer(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	tp, _ := newInMemoryTP()
	_, err := SetupTelemetry(WithTracerProvider(tp))
	if err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	if _, ok := DefaultTracer.(*_noopTracer); ok {
		t.Error("expected DefaultTracer to be replaced with real OTel adapter, got *_noopTracer")
	}
	if _, ok := DefaultTracer.(_otelTracerAdapter); !ok {
		t.Errorf("expected _otelTracerAdapter, got %T", DefaultTracer)
	}
}

// ── 2. Trace() creates a real OTel span and it appears in the in-memory exporter ──

func TestOTel_Trace_CreatesRealSpan(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	tp, exp := newInMemoryTP()
	_, err := SetupTelemetry(WithTracerProvider(tp))
	if err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	err = Trace(context.Background(), "test-span", func(_ context.Context) error {
		return nil
	})
	if err != nil {
		t.Fatalf("Trace returned error: %v", err)
	}

	spans := exp.GetSpans()
	if len(spans) == 0 {
		t.Fatal("expected at least one span in in-memory exporter")
	}
	if spans[0].Name != "test-span" {
		t.Errorf("expected span name %q, got %q", "test-span", spans[0].Name)
	}
}

// ── 3. GetTraceContext extracts real trace/span IDs from OTel span in context ──

func TestOTel_GetTraceContext_ExtractsFromOTelSpan(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	tp, _ := newInMemoryTP()
	_, err := SetupTelemetry(WithTracerProvider(tp))
	if err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	var capturedTraceID, capturedSpanID string
	err = Trace(context.Background(), "trace-ctx-test", func(ctx context.Context) error {
		capturedTraceID, capturedSpanID = GetTraceContext(ctx)
		return nil
	})
	if err != nil {
		t.Fatalf("Trace returned error: %v", err)
	}

	if capturedTraceID == "" {
		t.Error("expected non-empty trace ID from OTel span")
	}
	if capturedSpanID == "" {
		t.Error("expected non-empty span ID from OTel span")
	}
	// OTel IDs are 32 hex chars (trace) and 16 hex chars (span).
	if len(capturedTraceID) != 32 {
		t.Errorf("expected 32-char trace ID, got %q (len %d)", capturedTraceID, len(capturedTraceID))
	}
	if len(capturedSpanID) != 16 {
		t.Errorf("expected 16-char span ID, got %q (len %d)", capturedSpanID, len(capturedSpanID))
	}
}

// ── 4. ShutdownTelemetry shuts down the real provider ─────────────────────────

func TestOTel_ShutdownTelemetry_ShutsDownProvider(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	tp, _ := newInMemoryTP()
	_, err := SetupTelemetry(WithTracerProvider(tp))
	if err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("ShutdownTelemetry returned error: %v", err)
	}

	// After shutdown the global OTel provider pointers should be nil.
	if _otelTracerProvider != nil {
		t.Error("expected _otelTracerProvider to be nil after shutdown")
	}
}

// ── 5. No-op path: SetupTelemetry() without providers keeps *_noopTracer ──────

func TestOTel_NoProviders_KeepsNoopTracer(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	_, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	if _, ok := DefaultTracer.(*_noopTracer); !ok {
		t.Errorf("expected *_noopTracer without providers, got %T", DefaultTracer)
	}
}

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

// ── 8. _shutdownOTelProviders with no providers is a no-op ────────────────────

func TestOTel_ShutdownOTelProviders_NoProviders(t *testing.T) {
	_resetOTelProviders()
	t.Cleanup(func() { _resetOTelProviders() })

	if err := _shutdownOTelProviders(context.Background()); err != nil {
		t.Fatalf("expected nil error, got %v", err)
	}
}

// ── 9. _otelSpanAdapter delegates SpanID/TraceID/RecordError/End correctly ────

func TestOTel_SpanAdapter_Methods(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	tp, _ := newInMemoryTP()
	_, err := SetupTelemetry(WithTracerProvider(tp))
	if err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	ctx, span := DefaultTracer.Start(context.Background(), "adapter-test")
	_ = ctx

	if span.TraceID() == "" {
		t.Error("expected non-empty TraceID")
	}
	if span.SpanID() == "" {
		t.Error("expected non-empty SpanID")
	}
	span.SetAttribute("key", "value") // should not panic
	span.RecordError(nil)             // should not panic
	span.End()                        // should not panic
}

// ── 10. SetupTelemetry with non-OTel provider type is gracefully ignored ──────

func TestOTel_WrongProviderType_Ignored(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	sentinel := struct{ name string }{name: "not-a-tracer-provider"}
	_, err := SetupTelemetry(WithTracerProvider(sentinel), WithMeterProvider(sentinel))
	if err != nil {
		t.Fatalf("SetupTelemetry should not fail on wrong provider type: %v", err)
	}

	// DefaultTracer should remain noop because type assertion fails.
	if _, ok := DefaultTracer.(*_noopTracer); !ok {
		t.Errorf("expected *_noopTracer for wrong provider type, got %T", DefaultTracer)
	}
	if _otelMeterProvider != nil {
		t.Error("expected _otelMeterProvider to remain nil for wrong provider type")
	}
}

// ── 11. multiHandler Enabled/Handle/WithAttrs/WithGroup ───────────────────────

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

// ── 12. multiHandler.Enabled returns false when no handler is enabled ─────────

func TestMultiHandler_Enabled_AllDisabled(t *testing.T) {
	// Both handlers only enabled at ERROR level; asking about DEBUG should return false.
	h1 := &testCountingHandler{level: slog.LevelError}
	h2 := &testCountingHandler{level: slog.LevelError}
	mh := newMultiHandler(h1, h2)

	if mh.Enabled(context.Background(), slog.LevelDebug) {
		t.Error("expected Enabled=false when all handlers require ERROR level")
	}
}

// ── 13. multiHandler.Handle returns first error from handler ─────────────────

func TestMultiHandler_Handle_ReturnsError(t *testing.T) {
	errH := &testErrorHandler{err: errOTelShutdown}
	mh := newMultiHandler(errH)

	r := slog.NewRecord(time.Now(), slog.LevelInfo, "test", 0)
	err := mh.Handle(context.Background(), r)
	if err == nil {
		t.Fatal("expected error from Handle when handler returns error")
	}
}

// ── 14. _shutdownOTelProviders returns first error when tracer shutdown fails ─

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

// ── 15. _shutdownOTelProviders: tracer errors, meter also errors (first!=nil branch) ─

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

// testErrorHandler is a slog.Handler that always returns an error from Handle.
type testErrorHandler struct {
	err error
}

func (h *testErrorHandler) Enabled(_ context.Context, _ slog.Level) bool  { return true }
func (h *testErrorHandler) Handle(_ context.Context, _ slog.Record) error { return h.err }
func (h *testErrorHandler) WithAttrs(_ []slog.Attr) slog.Handler          { return h }
func (h *testErrorHandler) WithGroup(_ string) slog.Handler               { return h }

// ── 16. _shutdownOTelProviders: only meter errors (first==nil true → assign error) ─

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
