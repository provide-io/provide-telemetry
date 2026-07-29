// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"testing"
	"time"

	otellog "go.opentelemetry.io/otel/log"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

const _stallPerSignal = 250 * time.Millisecond

// _slowSpanExporter and _slowLogExporter each take _stallPerSignal to export,
// standing in for an exporter waiting on a slow collector.
type _slowSpanExporter struct{}

func (_slowSpanExporter) ExportSpans(context.Context, []sdktrace.ReadOnlySpan) error {
	time.Sleep(_stallPerSignal)
	return nil
}
func (_slowSpanExporter) Shutdown(context.Context) error { return nil }

type _slowLogExporter struct{}

func (_slowLogExporter) Export(context.Context, []sdklog.Record) error {
	time.Sleep(_stallPerSignal)
	return nil
}
func (_slowLogExporter) Shutdown(context.Context) error   { return nil }
func (_slowLogExporter) ForceFlush(context.Context) error { return nil }

// Each signal must get the caller's full budget. Run in sequence they share one
// deadline, so a slow first exporter eats it and the rest return
// DeadlineExceeded without exporting anything.
func TestForceFlush_SignalsDrainConcurrently(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	tp := sdktrace.NewTracerProvider(sdktrace.WithBatcher(_slowSpanExporter{}))
	lp := sdklog.NewLoggerProvider(sdklog.WithProcessor(sdklog.NewBatchProcessor(_slowLogExporter{})))
	_otelTracerProvider = tp
	_otelLoggerProvider = lp
	t.Cleanup(func() {
		_ = tp.Shutdown(context.Background())
		_ = lp.Shutdown(context.Background())
	})

	// Give each signal something to export so ForceFlush actually reaches the
	// exporter rather than returning on an empty queue.
	_, span := tp.Tracer("flush.concurrent").Start(context.Background(), "queued")
	span.End()
	lp.Logger("flush.concurrent").Emit(context.Background(), otellog.Record{})

	start := time.Now()
	if err := (&_backend{}).ForceFlush(context.Background()); err != nil {
		t.Fatalf("ForceFlush returned %v, want nil", err)
	}
	elapsed := time.Since(start)

	// Sequential would be >= 2x the per-signal stall; concurrent is ~1x.
	if elapsed >= 2*_stallPerSignal {
		t.Errorf("ForceFlush took %v for two %v signals — they drained in sequence, not concurrently",
			elapsed, _stallPerSignal)
	}
}
