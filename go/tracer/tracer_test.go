// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package tracer_test

import (
	"context"
	"errors"
	"testing"

	"github.com/provide-io/provide-telemetry/go/tracer"
	oteltrace "go.opentelemetry.io/otel/trace"
)

func TestNoopSpan(t *testing.T) {
	ctx, span := tracer.DefaultTracer.Start(context.Background(), "test.op")
	if span == nil {
		t.Fatal("Start should return a non-nil span")
	}
	if span.TraceID() == "" {
		t.Fatal("TraceID should be non-empty")
	}
	if span.SpanID() == "" {
		t.Fatal("SpanID should be non-empty")
	}

	// Span methods should not panic.
	span.SetAttribute("key", "value")
	span.RecordError(errors.New("test error"))
	span.End()

	// TraceID and SpanID should appear in context.
	traceID, spanID := tracer.GetTraceContext(ctx)
	if traceID == "" || spanID == "" {
		t.Fatalf("trace context not set: trace=%q span=%q", traceID, spanID)
	}
}

func TestGetTracer(t *testing.T) {
	tr := tracer.GetTracer("my-service")
	if tr == nil {
		t.Fatal("GetTracer should not return nil")
	}
}

func TestTraceSuccess(t *testing.T) {
	called := false
	err := tracer.Trace(context.Background(), "test.op", func(ctx context.Context) error {
		called = true
		traceID, spanID := tracer.GetTraceContext(ctx)
		if traceID == "" || spanID == "" {
			t.Errorf("trace context not available inside Trace: trace=%q span=%q", traceID, spanID)
		}
		return nil
	})
	if err != nil {
		t.Fatalf("Trace returned error: %v", err)
	}
	if !called {
		t.Fatal("fn was not called")
	}
}

func TestTraceError(t *testing.T) {
	sentinel := errors.New("inner error")
	err := tracer.Trace(context.Background(), "test.op", func(_ context.Context) error {
		return sentinel
	})
	if !errors.Is(err, sentinel) {
		t.Fatalf("expected sentinel error, got: %v", err)
	}
}

func TestSetTraceContext(t *testing.T) {
	ctx := tracer.SetTraceContext(context.Background(), "trace-abc", "span-def")
	traceID, spanID := tracer.GetTraceContext(ctx)
	if traceID != "trace-abc" || spanID != "span-def" {
		t.Fatalf("SetTraceContext: trace=%q span=%q", traceID, spanID)
	}
}

func TestGetTraceContextEmpty(t *testing.T) {
	traceID, spanID := tracer.GetTraceContext(context.Background())
	if traceID != "" || spanID != "" {
		t.Fatalf("fresh context should have empty trace IDs: trace=%q span=%q", traceID, spanID)
	}
}

func TestSetDefaultTracer(t *testing.T) {
	orig := tracer.DefaultTracer
	defer tracer.SetDefaultTracer(orig)

	custom := &_customTracer{}
	tracer.SetDefaultTracer(custom)
	if tracer.DefaultTracer != custom {
		t.Fatal("SetDefaultTracer should replace DefaultTracer")
	}
	if tracer.GetTracer("any") != custom {
		t.Fatal("GetTracer should return DefaultTracer")
	}
}

func TestNoopSpanIDsDifferentEachCall(t *testing.T) {
	_, s1 := tracer.DefaultTracer.Start(context.Background(), "op")
	_, s2 := tracer.DefaultTracer.Start(context.Background(), "op")
	if s1.TraceID() == s2.TraceID() {
		t.Fatal("different starts should produce different trace IDs")
	}
}

// TestGetTraceContextWithOTelSpan covers the OTel active span branch in GetTraceContext.
func TestGetTraceContextWithOTelSpan(t *testing.T) {
	traceID, err := oteltrace.TraceIDFromHex("01020304050607080102030405060708")
	if err != nil {
		t.Fatalf("TraceIDFromHex: %v", err)
	}
	spanID, err := oteltrace.SpanIDFromHex("0102030405060708")
	if err != nil {
		t.Fatalf("SpanIDFromHex: %v", err)
	}
	sc := oteltrace.NewSpanContext(oteltrace.SpanContextConfig{
		TraceID:    traceID,
		SpanID:     spanID,
		TraceFlags: oteltrace.FlagsSampled,
	})
	// Inject a fake span that returns our span context.
	ctx := oteltrace.ContextWithSpan(context.Background(), &_fakeOTelSpan{sc: sc})

	gotTraceID, gotSpanID := tracer.GetTraceContext(ctx)
	if gotTraceID == "" || gotSpanID == "" {
		t.Fatalf("expected non-empty IDs from OTel span, got trace=%q span=%q", gotTraceID, gotSpanID)
	}
}

// _fakeOTelSpan implements go.opentelemetry.io/otel/trace.Span with a fixed SpanContext.
type _fakeOTelSpan struct {
	oteltrace.Span
	sc oteltrace.SpanContext
}

func (f *_fakeOTelSpan) SpanContext() oteltrace.SpanContext { return f.sc }
func (f *_fakeOTelSpan) IsRecording() bool                 { return false }

// _customTracer is a test-only Tracer implementation.
type _customTracer struct{}

func (c *_customTracer) Start(ctx context.Context, _ string) (context.Context, tracer.Span) {
	return ctx, &_customSpan{}
}

type _customSpan struct{}

func (s *_customSpan) End()                               {}
func (s *_customSpan) SetAttribute(_ string, _ any)      {}
func (s *_customSpan) RecordError(_ error)                {}
func (s *_customSpan) SpanID() string                     { return "custom-span" }
func (s *_customSpan) TraceID() string                    { return "custom-trace" }
