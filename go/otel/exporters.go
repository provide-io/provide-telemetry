// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"

	telemetry "github.com/provide-io/provide-telemetry/go"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

type resilientSpanExporter struct {
	inner sdktrace.SpanExporter
}

func _wrapSpanExporter(inner sdktrace.SpanExporter) sdktrace.SpanExporter {
	return &resilientSpanExporter{inner: inner}
}

func (r *resilientSpanExporter) ExportSpans(ctx context.Context, spans []sdktrace.ReadOnlySpan) error {
	return telemetry.RunWithResilience(ctx, "traces", func(cctx context.Context) error {
		return r.inner.ExportSpans(cctx, spans)
	})
}

func (r *resilientSpanExporter) Shutdown(ctx context.Context) error {
	return r.inner.Shutdown(ctx)
}

type resilientLogExporter struct {
	inner sdklog.Exporter
}

func _wrapLogExporter(inner sdklog.Exporter) sdklog.Exporter {
	return &resilientLogExporter{inner: inner}
}

func (r *resilientLogExporter) Export(ctx context.Context, records []sdklog.Record) error {
	return telemetry.RunWithResilience(ctx, "logs", func(cctx context.Context) error {
		return r.inner.Export(cctx, records)
	})
}

func (r *resilientLogExporter) ForceFlush(ctx context.Context) error {
	return r.inner.ForceFlush(ctx)
}

func (r *resilientLogExporter) Shutdown(ctx context.Context) error {
	return r.inner.Shutdown(ctx)
}

type resilientMetricsExporter struct {
	inner sdkmetric.Exporter
}

func _wrapMetricsExporter(inner sdkmetric.Exporter) sdkmetric.Exporter {
	return &resilientMetricsExporter{inner: inner}
}

func (r *resilientMetricsExporter) Temporality(kind sdkmetric.InstrumentKind) metricdata.Temporality {
	return r.inner.Temporality(kind)
}

func (r *resilientMetricsExporter) Aggregation(kind sdkmetric.InstrumentKind) sdkmetric.Aggregation {
	return r.inner.Aggregation(kind)
}

func (r *resilientMetricsExporter) Export(ctx context.Context, data *metricdata.ResourceMetrics) error {
	return telemetry.RunWithResilience(ctx, "metrics", func(cctx context.Context) error {
		return r.inner.Export(cctx, data)
	})
}

func (r *resilientMetricsExporter) ForceFlush(ctx context.Context) error {
	return r.inner.ForceFlush(ctx)
}

func (r *resilientMetricsExporter) Shutdown(ctx context.Context) error {
	return r.inner.Shutdown(ctx)
}
