// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"errors"
	"sync/atomic"
	"testing"

	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

// ── fakes ─────────────────────────────────────────────────────────────────────

type _fakeSpanExporter struct {
	exports     atomic.Int32
	shutdowns   atomic.Int32
	exportErr   error
	shutdownErr error
}

func (f *_fakeSpanExporter) ExportSpans(_ context.Context, _ []sdktrace.ReadOnlySpan) error {
	f.exports.Add(1)
	return f.exportErr
}

func (f *_fakeSpanExporter) Shutdown(_ context.Context) error {
	f.shutdowns.Add(1)
	return f.shutdownErr
}

type _fakeLogExporter struct {
	exports    atomic.Int32
	flushes    atomic.Int32
	shutdowns  atomic.Int32
	exportErr  error
	flushErr   error
	shutdwnErr error
}

func (f *_fakeLogExporter) Export(_ context.Context, _ []sdklog.Record) error {
	f.exports.Add(1)
	return f.exportErr
}

func (f *_fakeLogExporter) ForceFlush(_ context.Context) error {
	f.flushes.Add(1)
	return f.flushErr
}

func (f *_fakeLogExporter) Shutdown(_ context.Context) error {
	f.shutdowns.Add(1)
	return f.shutdwnErr
}

type _fakeMetricsExporter struct {
	exports     atomic.Int32
	flushes     atomic.Int32
	shutdowns   atomic.Int32
	tempCalls   atomic.Int32
	aggCalls    atomic.Int32
	exportErr   error
	flushErr    error
	shutdownErr error
}

func (f *_fakeMetricsExporter) Temporality(_ sdkmetric.InstrumentKind) metricdata.Temporality {
	f.tempCalls.Add(1)
	return metricdata.CumulativeTemporality
}

func (f *_fakeMetricsExporter) Aggregation(_ sdkmetric.InstrumentKind) sdkmetric.Aggregation {
	f.aggCalls.Add(1)
	return sdkmetric.AggregationDefault{}
}

func (f *_fakeMetricsExporter) Export(_ context.Context, _ *metricdata.ResourceMetrics) error {
	f.exports.Add(1)
	return f.exportErr
}

func (f *_fakeMetricsExporter) ForceFlush(_ context.Context) error {
	f.flushes.Add(1)
	return f.flushErr
}

func (f *_fakeMetricsExporter) Shutdown(_ context.Context) error {
	f.shutdowns.Add(1)
	return f.shutdownErr
}

// ── spans ─────────────────────────────────────────────────────────────────────

func TestResilientSpanExporter_ExportsSuccessfullyForwardCalls(t *testing.T) {
	_resetResiliencePolicies()
	defer _resetResiliencePolicies()
	inner := &_fakeSpanExporter{}
	wrapped := _wrapSpanExporter(inner)
	if err := wrapped.ExportSpans(context.Background(), nil); err != nil {
		t.Fatalf("ExportSpans: %v", err)
	}
	if inner.exports.Load() != 1 {
		t.Fatalf("expected 1 inner call, got %d", inner.exports.Load())
	}
}

func TestResilientSpanExporter_FailOpenSwallowsInnerError(t *testing.T) {
	_resetResiliencePolicies()
	defer _resetResiliencePolicies()
	SetExporterPolicy("traces", ExporterPolicy{Retries: 0, BackoffSeconds: 0, TimeoutSeconds: 0, FailOpen: true})
	inner := &_fakeSpanExporter{exportErr: errors.New("boom")}
	wrapped := _wrapSpanExporter(inner)
	if err := wrapped.ExportSpans(context.Background(), nil); err != nil {
		t.Fatalf("fail_open should swallow error, got %v", err)
	}
	if inner.exports.Load() != 1 {
		t.Fatalf("expected 1 inner call, got %d", inner.exports.Load())
	}
}

func TestResilientSpanExporter_FailClosedSurfaceError(t *testing.T) {
	_resetResiliencePolicies()
	defer _resetResiliencePolicies()
	SetExporterPolicy("traces", ExporterPolicy{Retries: 0, BackoffSeconds: 0, TimeoutSeconds: 0, FailOpen: false})
	inner := &_fakeSpanExporter{exportErr: errors.New("boom")}
	wrapped := _wrapSpanExporter(inner)
	if err := wrapped.ExportSpans(context.Background(), nil); err == nil {
		t.Fatalf("fail_closed should propagate error")
	}
}

func TestResilientSpanExporter_ShutdownForwards(t *testing.T) {
	_resetResiliencePolicies()
	defer _resetResiliencePolicies()
	inner := &_fakeSpanExporter{}
	wrapped := _wrapSpanExporter(inner)
	if err := wrapped.Shutdown(context.Background()); err != nil {
		t.Fatalf("Shutdown: %v", err)
	}
	if inner.shutdowns.Load() != 1 {
		t.Fatalf("expected 1 shutdown call, got %d", inner.shutdowns.Load())
	}
}

// ── logs ──────────────────────────────────────────────────────────────────────

func TestResilientLogExporter_ExportsSuccessfullyForwardCalls(t *testing.T) {
	_resetResiliencePolicies()
	defer _resetResiliencePolicies()
	inner := &_fakeLogExporter{}
	wrapped := _wrapLogExporter(inner)
	if err := wrapped.Export(context.Background(), nil); err != nil {
		t.Fatalf("Export: %v", err)
	}
	if inner.exports.Load() != 1 {
		t.Fatalf("expected 1 inner export, got %d", inner.exports.Load())
	}
}

func TestResilientLogExporter_RetriesOnInnerFailure(t *testing.T) {
	_resetResiliencePolicies()
	defer _resetResiliencePolicies()
	SetExporterPolicy("logs", ExporterPolicy{Retries: 2, BackoffSeconds: 0, TimeoutSeconds: 0, FailOpen: true})
	inner := &_fakeLogExporter{exportErr: errors.New("boom")}
	wrapped := _wrapLogExporter(inner)
	if err := wrapped.Export(context.Background(), nil); err != nil {
		t.Fatalf("fail_open should swallow error, got %v", err)
	}
	// retries=2 ⇒ 1 initial + 2 retries = 3 inner calls
	if got := inner.exports.Load(); got != 3 {
		t.Fatalf("expected 3 inner calls, got %d", got)
	}
}

func TestResilientLogExporter_ForceFlushAndShutdownForward(t *testing.T) {
	_resetResiliencePolicies()
	defer _resetResiliencePolicies()
	inner := &_fakeLogExporter{}
	wrapped := _wrapLogExporter(inner)
	if err := wrapped.ForceFlush(context.Background()); err != nil {
		t.Fatalf("ForceFlush: %v", err)
	}
	if err := wrapped.Shutdown(context.Background()); err != nil {
		t.Fatalf("Shutdown: %v", err)
	}
	if inner.flushes.Load() != 1 || inner.shutdowns.Load() != 1 {
		t.Fatalf("expected 1 flush + 1 shutdown, got flush=%d shutdown=%d", inner.flushes.Load(), inner.shutdowns.Load())
	}
}

// ── metrics ───────────────────────────────────────────────────────────────────

func TestResilientMetricsExporter_ExportsSuccessfullyForwardCalls(t *testing.T) {
	_resetResiliencePolicies()
	defer _resetResiliencePolicies()
	inner := &_fakeMetricsExporter{}
	wrapped := _wrapMetricsExporter(inner)
	if err := wrapped.Export(context.Background(), nil); err != nil {
		t.Fatalf("Export: %v", err)
	}
	if inner.exports.Load() != 1 {
		t.Fatalf("expected 1 inner export, got %d", inner.exports.Load())
	}
}

func TestResilientMetricsExporter_TemporalityAndAggregationForward(t *testing.T) {
	_resetResiliencePolicies()
	defer _resetResiliencePolicies()
	inner := &_fakeMetricsExporter{}
	wrapped := _wrapMetricsExporter(inner)
	if got := wrapped.Temporality(sdkmetric.InstrumentKindCounter); got != metricdata.CumulativeTemporality {
		t.Fatalf("unexpected temporality: %v", got)
	}
	if got := wrapped.Aggregation(sdkmetric.InstrumentKindCounter); got == nil {
		t.Fatalf("Aggregation returned nil")
	}
	if inner.tempCalls.Load() != 1 || inner.aggCalls.Load() != 1 {
		t.Fatalf("expected forwarded calls, got temp=%d agg=%d", inner.tempCalls.Load(), inner.aggCalls.Load())
	}
}

func TestResilientMetricsExporter_FailClosedSurfaceError(t *testing.T) {
	_resetResiliencePolicies()
	defer _resetResiliencePolicies()
	SetExporterPolicy("metrics", ExporterPolicy{Retries: 0, BackoffSeconds: 0, TimeoutSeconds: 0, FailOpen: false})
	inner := &_fakeMetricsExporter{exportErr: errors.New("boom")}
	wrapped := _wrapMetricsExporter(inner)
	if err := wrapped.Export(context.Background(), nil); err == nil {
		t.Fatalf("fail_closed should propagate error")
	}
}

func TestResilientMetricsExporter_ForceFlushAndShutdownForward(t *testing.T) {
	_resetResiliencePolicies()
	defer _resetResiliencePolicies()
	inner := &_fakeMetricsExporter{}
	wrapped := _wrapMetricsExporter(inner)
	if err := wrapped.ForceFlush(context.Background()); err != nil {
		t.Fatalf("ForceFlush: %v", err)
	}
	if err := wrapped.Shutdown(context.Background()); err != nil {
		t.Fatalf("Shutdown: %v", err)
	}
	if inner.flushes.Load() != 1 || inner.shutdowns.Load() != 1 {
		t.Fatalf("expected forwarded calls, got flush=%d shutdown=%d", inner.flushes.Load(), inner.shutdowns.Load())
	}
}
