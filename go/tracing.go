// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"crypto/rand"
	"encoding/hex"
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

// _traceIDKey and _spanIDKey are context keys for trace/span propagation.
var (
	_traceIDKey = contextKey{"trace.id"} //nolint:gochecknoglobals
	_spanIDKey  = contextKey{"span.id"}  //nolint:gochecknoglobals
)

// GetTracer returns a named Tracer. Currently returns DefaultTracer.
func GetTracer(name string) Tracer {
	_ = name
	return DefaultTracer
}

// Trace wraps fn in a span using DefaultTracer.
// fn receives the context enriched with trace/span IDs.
// If fn returns an error, the error is recorded on the span before it ends.
// Consent, sampling, and backpressure are applied before starting the span;
// fn is still invoked (without a span) when any gate rejects.
func Trace(ctx context.Context, name string, fn func(context.Context) error) error {
	if !ShouldAllow(signalTraces, "") {
		return fn(ctx)
	}
	if sampled, _ := ShouldSample(signalTraces, name); !sampled {
		return fn(ctx)
	}
	if !TryAcquire(signalTraces) {
		return fn(ctx)
	}
	defer Release(signalTraces)
	_incSpansStarted()

	spanCtx, span := DefaultTracer.Start(ctx, name)
	defer span.End()
	err := fn(spanCtx)
	if err != nil {
		// Record exception to span; OTel spans forward this to the backend.
		span.RecordError(err)
	}
	return err
}

// GetTraceContext returns the trace and span IDs bound to ctx.
// When an active OTel span is present in ctx its IDs take precedence.
// Falls back to context key values set by SetTraceContext.
// Returns empty strings if not set.
func GetTraceContext(ctx context.Context) (traceID, spanID string) {
	if backend := _activeBackend(); backend != nil {
		if traceID, spanID, ok := backend.TraceContext(ctx); ok {
			return traceID, spanID
		}
	}
	if v, ok := ctx.Value(_traceIDKey).(string); ok {
		traceID = v
	}
	if v, ok := ctx.Value(_spanIDKey).(string); ok {
		spanID = v
	}
	return traceID, spanID
}

// SetTraceContext returns a new context with the given trace/span IDs bound.
func SetTraceContext(ctx context.Context, traceID, spanID string) context.Context {
	ctx = context.WithValue(ctx, _traceIDKey, traceID)
	ctx = context.WithValue(ctx, _spanIDKey, spanID)
	return ctx
}

// _getTraceSpanFromContext extracts trace/span IDs from context.
func _getTraceSpanFromContext(ctx context.Context) (traceID, spanID string) {
	return GetTraceContext(ctx)
}

// _setDefaultTracer replaces DefaultTracer (called by OTel integration in Task 14).
func _setDefaultTracer(t Tracer) {
	DefaultTracer = t
}
