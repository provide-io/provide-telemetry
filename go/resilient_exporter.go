// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"

	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

// resilientSpanExporter wraps an OTel SpanExporter so that every ExportSpans
// call runs under the per-signal retry/timeout/circuit-breaker policy defined
// in resilience.go. Without this wrapper the resilience contract is only
// enforced at exporter construction time — the documented invariant that every
// export goes through the policy would not hold for live transport traffic.
type resilientSpanExporter struct {
	inner  sdktrace.SpanExporter
	signal string
}

func _wrapSpanExporter(inner sdktrace.SpanExporter) sdktrace.SpanExporter {
	return &resilientSpanExporter{inner: inner, signal: "traces"}
}

// ExportSpans applies the traces resilience policy to every batch export.
func (r *resilientSpanExporter) ExportSpans(ctx context.Context, spans []sdktrace.ReadOnlySpan) error {
	return RunWithResilience(ctx, r.signal, func(cctx context.Context) error {
		return r.inner.ExportSpans(cctx, spans)
	})
}

// Shutdown delegates to the inner exporter without resilience framing.
func (r *resilientSpanExporter) Shutdown(ctx context.Context) error {
	return r.inner.Shutdown(ctx)
}

// resilientLogExporter wraps an OTel sdklog.Exporter and routes every Export
// call through the logs resilience policy.
type resilientLogExporter struct {
	inner  sdklog.Exporter
	signal string
}

func _wrapLogExporter(inner sdklog.Exporter) sdklog.Exporter {
	return &resilientLogExporter{inner: inner, signal: "logs"}
}

// Export applies the logs resilience policy to every batch export.
func (r *resilientLogExporter) Export(ctx context.Context, records []sdklog.Record) error {
	return RunWithResilience(ctx, r.signal, func(cctx context.Context) error {
		return r.inner.Export(cctx, records)
	})
}

// ForceFlush delegates to the inner exporter untouched.
func (r *resilientLogExporter) ForceFlush(ctx context.Context) error {
	return r.inner.ForceFlush(ctx)
}

// Shutdown delegates to the inner exporter untouched.
func (r *resilientLogExporter) Shutdown(ctx context.Context) error {
	return r.inner.Shutdown(ctx)
}

// resilientMetricsExporter wraps an OTel sdkmetric.Exporter. Temporality and
// Aggregation are delegated directly (they are synchronous configuration
// queries, not transport operations, so the resilience policy does not apply).
type resilientMetricsExporter struct {
	inner  sdkmetric.Exporter
	signal string
}

func _wrapMetricsExporter(inner sdkmetric.Exporter) sdkmetric.Exporter {
	return &resilientMetricsExporter{inner: inner, signal: "metrics"}
}

// Temporality forwards the configuration query to the inner exporter.
func (r *resilientMetricsExporter) Temporality(kind sdkmetric.InstrumentKind) metricdata.Temporality {
	return r.inner.Temporality(kind)
}

// Aggregation forwards the configuration query to the inner exporter.
func (r *resilientMetricsExporter) Aggregation(kind sdkmetric.InstrumentKind) sdkmetric.Aggregation {
	return r.inner.Aggregation(kind)
}

// Export applies the metrics resilience policy to every batch export.
func (r *resilientMetricsExporter) Export(ctx context.Context, data *metricdata.ResourceMetrics) error {
	return RunWithResilience(ctx, r.signal, func(cctx context.Context) error {
		return r.inner.Export(cctx, data)
	})
}

// ForceFlush delegates to the inner exporter untouched.
func (r *resilientMetricsExporter) ForceFlush(ctx context.Context) error {
	return r.inner.ForceFlush(ctx)
}

// Shutdown delegates to the inner exporter untouched.
func (r *resilientMetricsExporter) Shutdown(ctx context.Context) error {
	return r.inner.Shutdown(ctx)
}
