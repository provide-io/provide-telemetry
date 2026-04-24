// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"sync"
	"testing"

	telemetry "github.com/provide-io/provide-telemetry/go"
	otellog "go.opentelemetry.io/otel/log"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
)

func resetSetupState(t *testing.T) {
	t.Helper()
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
	t.Setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "")
	t.Setenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "")
	t.Setenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "")
	telemetry.ResetForTests()
}

func newInMemoryTP() (*sdktrace.TracerProvider, *tracetest.InMemoryExporter) {
	exp := tracetest.NewInMemoryExporter()
	tp := sdktrace.NewTracerProvider(sdktrace.WithSyncer(exp))
	return tp, exp
}

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

func (e *_inMemoryLogExporter) Shutdown(context.Context) error   { return nil }
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
