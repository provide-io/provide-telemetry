// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package tracer

import (
	"context"
	"crypto/rand"
	"encoding/hex"

	"github.com/provide-io/provide-telemetry/go/logger"
	oteltrace "go.opentelemetry.io/otel/trace"
)

// Span represents an active trace span.
type Span interface {
	End()
	SetAttribute(key string, value any)
	RecordError(err error)
	SpanID() string
	TraceID() string
}

// Tracer creates and manages spans.
type Tracer interface {
	Start(ctx context.Context, name string) (context.Context, Span)
}

// _noopSpan is a no-op Span implementation used when no real tracer is configured.
type _noopSpan struct {
	traceID string
	spanID  string
}

func (s *_noopSpan) End()                               { _ = s }
func (s *_noopSpan) SetAttribute(key string, value any) { _ = key; _ = value }
func (s *_noopSpan) RecordError(err error)              { _ = err }
func (s *_noopSpan) SpanID() string                     { return s.spanID }
func (s *_noopSpan) TraceID() string                    { return s.traceID }

// _noopTracer is a no-op Tracer that generates random IDs and stores them in context.
type _noopTracer struct{}

func (t *_noopTracer) Start(ctx context.Context, name string) (context.Context, Span) {
	_ = name
	traceID := _randomHex(16)
	spanID := _randomHex(8)
	ctx = SetTraceContext(ctx, traceID, spanID)
	return ctx, &_noopSpan{traceID: traceID, spanID: spanID}
}

// _randomHex returns a random hex string of n bytes (2n hex chars).
func _randomHex(n int) string {
	b := make([]byte, n)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// DefaultTracer is the package-level tracer, defaults to no-op.
var DefaultTracer Tracer = &_noopTracer{} //nolint:gochecknoglobals

// SetDefaultTracer replaces DefaultTracer. Called by the main telemetry package
// during OTel setup to wire in a real exporting tracer.
func SetDefaultTracer(t Tracer) {
	DefaultTracer = t
}

// GetTracer returns a named Tracer. Currently returns DefaultTracer.
func GetTracer(name string) Tracer {
	_ = name
	return DefaultTracer
}

// Trace wraps fn in a span using DefaultTracer.
// fn receives the context enriched with trace/span IDs.
// If fn returns an error the error is recorded on the span before it ends.
func Trace(ctx context.Context, name string, fn func(context.Context) error) error {
	spanCtx, span := DefaultTracer.Start(ctx, name)
	defer span.End()
	err := fn(spanCtx)
	if err != nil {
		span.RecordError(err)
	}
	return err
}

// SetTraceContext returns a new context with the given trace/span IDs bound.
// Delegates to the logger sub-package so that logger.GetTraceContext reads
// the same context keys without requiring an OTel dependency.
func SetTraceContext(ctx context.Context, traceID, spanID string) context.Context {
	return logger.SetTraceContext(ctx, traceID, spanID)
}

// GetTraceContext returns the trace and span IDs bound to ctx.
// When an active OTel span is present its IDs take precedence.
// Falls back to context key values set by SetTraceContext.
func GetTraceContext(ctx context.Context) (traceID, spanID string) {
	if span := oteltrace.SpanFromContext(ctx); span.SpanContext().IsValid() {
		sc := span.SpanContext()
		return sc.TraceID().String(), sc.SpanID().String()
	}
	return logger.GetTraceContext(ctx)
}
