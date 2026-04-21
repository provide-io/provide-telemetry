// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"testing"

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

// ── 1. WithTracerProvider wires real tracer ───────────────────────────────────

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

// ── 2. Trace() creates a real OTel span ──────────────────────────────────────

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

// ── 3. GetTraceContext extracts real trace/span IDs ───────────────────────────

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

func TestOTel_TraceEndpointAutoWiresTracerProvider(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://collector:4318")

	_, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	if _, ok := DefaultTracer.(*_noopTracer); ok {
		t.Fatal("expected env-configured traces endpoint to replace DefaultTracer with OTel adapter")
	}
	if _otelTracerProvider == nil {
		t.Fatal("expected env-configured traces endpoint to install tracer provider")
	}
}

func TestOTel_ShutdownTelemetry_RestoresNoopTracer(t *testing.T) {
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

	if _, ok := DefaultTracer.(*_noopTracer); !ok {
		t.Fatalf("expected DefaultTracer to be reset to noop after shutdown, got %T", DefaultTracer)
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

// ── 10. SetAttribute preserves native attribute types ─────────────────────────

func TestOTel_SpanAdapter_SetAttribute_TypedValues(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	tp, exp := newInMemoryTP()
	_, err := SetupTelemetry(WithTracerProvider(tp))
	if err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	ctx, span := DefaultTracer.Start(context.Background(), "attr-type-test")
	_ = ctx
	span.SetAttribute("b", true)
	span.SetAttribute("i", 42)
	span.SetAttribute("i64", int64(1000))
	span.SetAttribute("f64", 3.14)
	span.SetAttribute("s", "hello")
	span.SetAttribute("other", struct{}{})
	span.End()

	spans := exp.GetSpans()
	if len(spans) == 0 {
		t.Fatal("no spans recorded")
	}
	attrs := map[string]interface{}{}
	for _, kv := range spans[0].Attributes {
		attrs[string(kv.Key)] = kv.Value.AsInterface()
	}

	if v, ok := attrs["b"]; !ok || v != true {
		t.Errorf("bool attr: got %v (%T), want true", attrs["b"], attrs["b"])
	}
	if v, ok := attrs["i"]; !ok || v != int64(42) {
		t.Errorf("int attr: got %v (%T), want int64(42)", attrs["i"], attrs["i"])
	}
	if v, ok := attrs["i64"]; !ok || v != int64(1000) {
		t.Errorf("int64 attr: got %v (%T), want int64(1000)", attrs["i64"], attrs["i64"])
	}
	if v, ok := attrs["f64"]; !ok || v != 3.14 {
		t.Errorf("float64 attr: got %v (%T), want 3.14", attrs["f64"], attrs["f64"])
	}
	if v, ok := attrs["s"]; !ok || v != "hello" {
		t.Errorf("string attr: got %v (%T), want \"hello\"", attrs["s"], attrs["s"])
	}
	if _, ok := attrs["other"]; !ok {
		t.Error("other attr: missing from span")
	}
}

// ── 11. SetupTelemetry with non-OTel provider type is gracefully ignored ──────

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

// ── 17. Logger becomes multiHandler after OTel wiring ────────────────────────

func TestOTel_LogBridge_AddedWhenLoggerSet(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	tp, _ := newInMemoryTP()
	_, err := SetupTelemetry(WithTracerProvider(tp))
	if err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	if _, ok := Logger.Handler().(*multiHandler); !ok {
		t.Errorf("expected *multiHandler after OTel wiring (bridge attached), got %T", Logger.Handler())
	}
}

// ── 18. _shutdownOTelProviders: only tracer errors returns that error ─────────

func TestOTel_ShutdownOTelProviders_OnlyTracerError(t *testing.T) {
	_resetOTelProviders()
	t.Cleanup(func() { _resetOTelProviders() })

	tp, _ := newInMemoryTP()
	_otelTracerProvider = tp
	// No meter provider set.

	cancelledCtx, cancel := context.WithCancel(context.Background())
	cancel() // cancel immediately to force tracer shutdown error

	err := _shutdownOTelProviders(cancelledCtx)
	if err == nil {
		t.Error("expected non-nil error when only tracer provider shutdown fails")
	}
}
