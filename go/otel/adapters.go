// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"fmt"
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

func (s *_otelSpanAdapter) SetAttribute(key string, value any) {
	var kv attribute.KeyValue
	switch v := value.(type) {
	case bool:
		kv = attribute.Bool(key, v)
	case int:
		kv = attribute.Int64(key, int64(v))
	case int64:
		kv = attribute.Int64(key, v)
	case float64:
		kv = attribute.Float64(key, v)
	case string:
		kv = attribute.String(key, v)
	default:
		kv = attribute.String(key, fmt.Sprintf("%v", value))
	}
	s.inner.SetAttributes(kv)
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
