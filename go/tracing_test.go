// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"errors"
	"testing"
)

// ── 1. GetTracer returns non-nil Tracer ───────────────────────────────────────

func TestGetTracer_NotNil(t *testing.T) {
	tr := GetTracer("test")
	if tr == nil {
		t.Fatal("GetTracer returned nil")
	}
}

// ── 2. DefaultTracer is the no-op by default ─────────────────────────────────

func TestDefaultTracer_IsNoop(t *testing.T) {
	if DefaultTracer == nil {
		t.Fatal("DefaultTracer is nil")
	}
	if _, ok := DefaultTracer.(*_noopTracer); !ok {
		t.Errorf("expected *_noopTracer, got %T", DefaultTracer)
	}
}

// ── 3. _noopTracer.Start returns span with non-empty IDs ─────────────────────

func TestNoopTracer_Start_NonEmptyIDs(t *testing.T) {
	tr := &_noopTracer{}
	_, span := tr.Start(context.Background(), "test-span")
	if span.TraceID() == "" {
		t.Error("expected non-empty TraceID from noopTracer.Start")
	}
	if span.SpanID() == "" {
		t.Error("expected non-empty SpanID from noopTracer.Start")
	}
}

// ── 4. _noopTracer.Start stores IDs in context ───────────────────────────────

func TestNoopTracer_Start_SetsContext(t *testing.T) {
	tr := &_noopTracer{}
	ctx, span := tr.Start(context.Background(), "test-span")
	traceID, spanID := GetTraceContext(ctx)
	if traceID != span.TraceID() {
		t.Errorf("context traceID %q != span TraceID %q", traceID, span.TraceID())
	}
	if spanID != span.SpanID() {
		t.Errorf("context spanID %q != span SpanID %q", spanID, span.SpanID())
	}
}

// ── Trace() enforcement gate tests ───────────────────────────────────────────

func TestTrace_SamplingZero_FnStillRuns(t *testing.T) {
	_resetSamplingPolicies()
	_resetHealth()
	t.Cleanup(_resetSamplingPolicies)
	t.Cleanup(_resetHealth)
	_, err := SetSamplingPolicy(signalTraces, SamplingPolicy{DefaultRate: 0})
	if err != nil {
		t.Fatal(err)
	}

	ran := false
	_ = Trace(context.Background(), "test.span", func(_ context.Context) error {
		ran = true
		return nil
	})
	if !ran {
		t.Error("expected fn to run even when sampling rate is 0")
	}
	snap := GetHealthSnapshot()
	if snap.TracesEmitted != 0 {
		t.Errorf("expected TracesEmitted=0 when sampling=0, got %d", snap.TracesEmitted)
	}
}

func TestTrace_BackpressureFull_FnStillRuns(t *testing.T) {
	_resetQueuePolicy()
	_resetHealth()
	t.Cleanup(_resetQueuePolicy)
	t.Cleanup(_resetHealth)
	SetQueuePolicy(QueuePolicy{TracesMaxSize: 1})
	ok := TryAcquire(signalTraces)
	if !ok {
		t.Fatal("could not acquire initial trace slot")
	}
	defer Release(signalTraces)

	ran := false
	_ = Trace(context.Background(), "test.span", func(_ context.Context) error {
		ran = true
		return nil
	})
	if !ran {
		t.Error("expected fn to run even under full backpressure")
	}
}

// ── 5. Span methods don't panic ───────────────────────────────────────────────

func TestNoopSpan_Methods_NoPanic(t *testing.T) {
	s := &_noopSpan{traceID: "abc", spanID: "def"}
	s.End()
	s.SetAttribute("key", "value")
	s.RecordError(errors.New("test error"))
}

// ── 6. _noopSpan.SpanID and TraceID return set values ────────────────────────

func TestNoopSpan_IDAccessors(t *testing.T) {
	s := &_noopSpan{traceID: "trace-123", spanID: "span-456"}
	if s.TraceID() != "trace-123" {
		t.Errorf("TraceID() = %q, want %q", s.TraceID(), "trace-123")
	}
	if s.SpanID() != "span-456" {
		t.Errorf("SpanID() = %q, want %q", s.SpanID(), "span-456")
	}
}

// ── 7. GetTraceContext on context without trace returns empty strings ─────────

func TestGetTraceContext_Empty(t *testing.T) {
	traceID, spanID := GetTraceContext(context.Background())
	if traceID != "" || spanID != "" {
		t.Errorf("expected empty strings, got traceID=%q spanID=%q", traceID, spanID)
	}
}

// ── 8. SetTraceContext + GetTraceContext round-trip ───────────────────────────

func TestSetGetTraceContext_RoundTrip(t *testing.T) {
	ctx := SetTraceContext(context.Background(), "t-id-1", "s-id-1")
	traceID, spanID := GetTraceContext(ctx)
	if traceID != "t-id-1" {
		t.Errorf("traceID = %q, want %q", traceID, "t-id-1")
	}
	if spanID != "s-id-1" {
		t.Errorf("spanID = %q, want %q", spanID, "s-id-1")
	}
}

// ── 9. Trace wraps fn and fn receives context with trace IDs set ──────────────

func TestTrace_ContextHasTraceIDs(t *testing.T) {
	var capturedTraceID, capturedSpanID string
	err := Trace(context.Background(), "op", func(ctx context.Context) error {
		capturedTraceID, capturedSpanID = GetTraceContext(ctx)
		return nil
	})
	if err != nil {
		t.Fatalf("Trace returned unexpected error: %v", err)
	}
	if capturedTraceID == "" {
		t.Error("expected non-empty traceID inside fn")
	}
	if capturedSpanID == "" {
		t.Error("expected non-empty spanID inside fn")
	}
}

// ── 10. Trace propagates fn error ─────────────────────────────────────────────

func TestTrace_PropagatesError(t *testing.T) {
	sentinel := errors.New("fn error")
	err := Trace(context.Background(), "op", func(_ context.Context) error {
		return sentinel
	})
	if !errors.Is(err, sentinel) {
		t.Errorf("expected sentinel error, got %v", err)
	}
}

// ── 11. _setDefaultTracer replaces DefaultTracer ──────────────────────────────

func TestSetDefaultTracer_Replaces(t *testing.T) {
	orig := DefaultTracer
	t.Cleanup(func() { DefaultTracer = orig })

	custom := &_noopTracer{}
	_setDefaultTracer(custom)

	if DefaultTracer != custom {
		t.Error("_setDefaultTracer did not replace DefaultTracer")
	}
}

// ── 12. GetTracer returns DefaultTracer after replacement ─────────────────────

func TestGetTracer_ReturnsDefaultTracer(t *testing.T) {
	orig := DefaultTracer
	t.Cleanup(func() { DefaultTracer = orig })

	custom := &_noopTracer{}
	_setDefaultTracer(custom)

	if GetTracer("any") != custom {
		t.Error("GetTracer did not return updated DefaultTracer")
	}
}
