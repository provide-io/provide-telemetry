// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"sync"
	"testing"

	otellog "go.opentelemetry.io/otel/log"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
)

type _inMemoryLogExporter struct {
	mu      sync.Mutex
	records []sdklog.Record
}

func (e *_inMemoryLogExporter) Export(_ context.Context, records []sdklog.Record) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	for _, record := range records {
		e.records = append(e.records, record.Clone())
	}
	return nil
}

func (e *_inMemoryLogExporter) Shutdown(context.Context) error { return nil }

func (e *_inMemoryLogExporter) ForceFlush(context.Context) error { return nil }

func (e *_inMemoryLogExporter) bodies() []string {
	e.mu.Lock()
	defer e.mu.Unlock()
	bodies := make([]string, 0, len(e.records))
	for _, record := range e.records {
		body := record.Body()
		if body.Kind() == otellog.KindString {
			bodies = append(bodies, body.AsString())
			continue
		}
		bodies = append(bodies, body.String())
	}
	return bodies
}

func TestOTel_GetLogger_EmitsThroughLoggerProvider(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	exporter := &_inMemoryLogExporter{}
	lp := sdklog.NewLoggerProvider(sdklog.WithProcessor(sdklog.NewSimpleProcessor(exporter)))

	if _, err := SetupTelemetry(WithLoggerProvider(lp)); err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	GetLogger(context.Background(), "integration.bridge").Info("otel facade logger bridge")

	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("ShutdownTelemetry failed: %v", err)
	}

	bodies := exporter.bodies()
	if len(bodies) == 0 {
		t.Fatal("expected GetLogger() output to be exported through the OTel log bridge")
	}
	found := false
	for _, body := range bodies {
		if body == "otel facade logger bridge" {
			found = true
			break
		}
	}
	if !found {
		t.Fatalf("expected exported log body %q, got %v", "otel facade logger bridge", bodies)
	}
}

func TestOTel_NewCounter_RecordsThroughMeterProvider(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	reader := sdkmetric.NewManualReader()
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader))

	if _, err := SetupTelemetry(WithMeterProvider(mp)); err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	NewCounter("otel.facade.counter", WithDescription("facade counter"), WithUnit("1")).Add(context.Background(), 5)

	var rm metricdata.ResourceMetrics
	if err := reader.Collect(context.Background(), &rm); err != nil {
		t.Fatalf("Collect failed: %v", err)
	}

	var total int64
	for _, scopeMetrics := range rm.ScopeMetrics {
		for _, metric := range scopeMetrics.Metrics {
			if metric.Name != "otel.facade.counter" {
				continue
			}
			sum, ok := metric.Data.(metricdata.Sum[int64])
			if !ok {
				t.Fatalf("expected int64 sum aggregation for %q, got %T", metric.Name, metric.Data)
			}
			for _, point := range sum.DataPoints {
				total += point.Value
			}
		}
	}

	if total != 5 {
		t.Fatalf("expected provider-backed counter export total 5, got %d", total)
	}
}
