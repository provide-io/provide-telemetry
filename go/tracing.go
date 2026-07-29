// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"sync/atomic"
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

// _defaultTracer is the package-level tracer binding, defaulting to no-op.
//
// An atomic rather than an exported variable: it is read from every traced call
// and written during SetupTelemetry and ShutdownTelemetry, and a two-word
// interface value read while it is being written can tear into a stale itab
// paired with a new data pointer. An atomic load is ~1ns against the ~20ns a
// RWMutex costs on that path, and the same reasoning already applies to the
// signal gates in runtime.go.
//
// Reachable through [GetTracer] and replaceable through [SetDefaultTracer]; the
// spec's "tracer instance" symbol is satisfied by the exported [Tracer] type.
var _defaultTracer atomic.Pointer[Tracer] //nolint:gochecknoglobals

func _loadDefaultTracer() Tracer {
	if bound := _defaultTracer.Load(); bound != nil {
		return *bound
	}
	return _noopTracerSingleton
}

// _noopTracerSingleton is the binding before any setup, and after teardown.
var _noopTracerSingleton Tracer = &_noopTracer{} //nolint:gochecknoglobals

// SetDefaultTracer replaces the package-level tracer.
//
// Exported so a host can install its own implementation; SetupTelemetry and
// ShutdownTelemetry use it too. Safe to call concurrently with in-flight spans.
func SetDefaultTracer(t Tracer) {
	_defaultTracer.Store(&t)
}

// _traceIDKey and _spanIDKey are context keys for trace/span propagation.
var (
	_traceIDKey = contextKey{"trace.id"} //nolint:gochecknoglobals
	_spanIDKey  = contextKey{"span.id"}  //nolint:gochecknoglobals
)

// GetTracer returns a named Tracer. Currently returns the package-level tracer.
func GetTracer(name string) Tracer {
	_ = name
	return _loadDefaultTracer()
}

// Trace wraps fn in a span using the package-level tracer.
// fn receives the context enriched with trace/span IDs.
// If fn returns an error, the error is recorded on the span before it ends.
// Consent, sampling, and backpressure are applied before starting the span;
// fn is still invoked (without a span) when any gate rejects.
//
// When a live OTel tracer provider is installed, probabilistic sampling is
// delegated to the SDK ParentBased(TraceIDRatioBased) sampler so instrumented
// and facade spans share one sampling authority (no double-sampling).
// Without a live provider, ShouldSample(traces) applies as before.
func Trace(ctx context.Context, name string, fn func(context.Context) error) error {
	if !TracingEnabled() {
		return fn(ctx)
	}
	if !ShouldAllow(signalTraces, "") {
		return fn(ctx)
	}
	if !_hasLiveTraceProvider() {
		if sampled := _shouldSampleFailOpen(signalTraces, name); !sampled {
			return fn(ctx)
		}
	}
	ticket := TryAcquire(signalTraces)
	if ticket == nil {
		return fn(ctx)
	}
	defer Release(ticket)
	_incSpansStarted()

	spanCtx, span := _effectiveTracer().Start(ctx, name)
	defer span.End()
	err := fn(spanCtx)
	if err != nil {
		// Record exception to span; OTel spans forward this to the backend.
		span.RecordError(err)
	}
	return err
}

// _hasLiveTraceProvider reports whether a live tracer provider is in play — ours
// or a host application's — in which case the SDK's sampler is authoritative and
// the facade must not stack its own rate on top.
//
// Answered by the backend, which reports both what it installed and what it
// found on the OTel globals, and re-asked per span so a provider registered
// after setup counts (see _effectiveTracer and go/otel/adopt.go). The gate and
// the emit path therefore read the same state: a span is never sampled by the
// facade and then handed to an SDK sampler, nor vice versa.
func _hasLiveTraceProvider() bool {
	backend := _activeBackend()
	if backend == nil {
		return false
	}
	return backend.Providers().Traces
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
