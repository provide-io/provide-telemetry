// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"log/slog"

	telemetry "github.com/provide-io/provide-telemetry/go"
	"go.opentelemetry.io/otel/attribute"
	otelmetric "go.opentelemetry.io/otel/metric"
	oteltrace "go.opentelemetry.io/otel/trace"
)

type _otelTracerAdapter struct {
	inner oteltrace.Tracer
}

func (a _otelTracerAdapter) Start(ctx context.Context, name string) (context.Context, telemetry.Span) {
	ctx, span := a.inner.Start(ctx, name)
	sc := span.SpanContext()
	ctx = telemetry.SetTraceContext(ctx, sc.TraceID().String(), sc.SpanID().String())
	return ctx, &_otelSpanAdapter{inner: span}
}

type _otelSpanAdapter struct {
	inner oteltrace.Span
}

func (s *_otelSpanAdapter) End() { s.inner.End() }

// SetAttribute bounds a span attribute before it leaves the process.
//
// Span attributes arrive as an untyped any straight from the caller and never
// pass through the logger's handler chain, so this is the only place they can
// be hardened: an unbounded string, a control character or a self-referential
// struct is otherwise the exporter's problem.
func (s *_otelSpanAdapter) SetAttribute(key string, value any) {
	s.inner.SetAttributes(_spanAttribute(key, telemetry.Harden(value, telemetry.DefaultLimits())))
}

// _spanAttribute maps a hardened value onto an OTel attribute type. Hardening
// has already collapsed every integer to int64 and every float to float64,
// which is why there is no int or float32 case: neither can arrive any more.
func _spanAttribute(key string, hardened any) attribute.KeyValue {
	switch v := hardened.(type) {
	case bool:
		return attribute.Bool(key, v)
	case int64:
		return attribute.Int64(key, v)
	case float64:
		return attribute.Float64(key, v)
	case string:
		return attribute.String(key, v)
	default:
		// nil, unsigned integers and every composite: OTel has no attribute
		// type for these, so they travel as canonical JSON rather than as
		// whatever %v happened to print for the caller's concrete type.
		return attribute.String(key, telemetry.CanonicalJSON(hardened))
	}
}

func (s *_otelSpanAdapter) RecordError(err error) { s.inner.RecordError(err) }
func (s *_otelSpanAdapter) SpanID() string        { return s.inner.SpanContext().SpanID().String() }
func (s *_otelSpanAdapter) TraceID() string       { return s.inner.SpanContext().TraceID().String() }

type _otelCounter struct {
	inner otelmetric.Int64Counter
}

func (c *_otelCounter) Add(ctx context.Context, value int64, attrs ...slog.Attr) {
	c.inner.Add(ctx, value, _addOptions(attrs)...)
}

type _otelGauge struct {
	inner otelmetric.Float64Gauge
}

func (g *_otelGauge) Set(ctx context.Context, value float64, attrs ...slog.Attr) {
	g.inner.Record(ctx, value, _recordOptions(attrs)...)
}

type _otelHistogram struct {
	inner otelmetric.Float64Histogram
}

func (h *_otelHistogram) Record(ctx context.Context, value float64, attrs ...slog.Attr) {
	h.inner.Record(ctx, value, _recordOptions(attrs)...)
}
