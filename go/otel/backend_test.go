// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"testing"

	telemetry "github.com/provide-io/provide-telemetry/go"
	"go.opentelemetry.io/otel"
	logglobal "go.opentelemetry.io/otel/log/global"
	otelmetricnoop "go.opentelemetry.io/otel/metric/noop"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
	otelnooptrace "go.opentelemetry.io/otel/trace/noop"
)

func TestOTel_WithTracerProvider_WiresRealTracer(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	tp, _ := newInMemoryTP()
	if _, err := telemetry.SetupTelemetry(telemetry.WithTracerProvider(tp)); err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	if _, ok := telemetry.DefaultTracer.(_otelTracerAdapter); !ok {
		t.Fatalf("expected OTel tracer adapter, got %T", telemetry.DefaultTracer)
	}
	if _otelTracerProvider == nil {
		t.Fatal("expected OTel tracer provider to be installed")
	}
}

func TestOTel_Trace_CreatesRealSpanAndTraceContext(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	tp, exp := newInMemoryTP()
	if _, err := telemetry.SetupTelemetry(telemetry.WithTracerProvider(tp)); err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	var traceID string
	var spanID string
	err := telemetry.Trace(context.Background(), "otel.test.span", func(ctx context.Context) error {
		traceID, spanID = telemetry.GetTraceContext(ctx)
		return nil
	})
	if err != nil {
		t.Fatalf("Trace returned error: %v", err)
	}

	spans := exp.GetSpans()
	if len(spans) != 1 {
		t.Fatalf("expected 1 span, got %d", len(spans))
	}
	if spans[0].Name != "otel.test.span" {
		t.Fatalf("expected span name %q, got %q", "otel.test.span", spans[0].Name)
	}
	if traceID == "" || spanID == "" {
		t.Fatalf("expected trace/span IDs from context, got %q/%q", traceID, spanID)
	}
}

func TestOTel_NoProvidersKeepsFallbackRuntime(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := telemetry.SetupTelemetry(); err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	status := telemetry.GetRuntimeStatus()
	if status.Providers.Logs || status.Providers.Traces || status.Providers.Metrics {
		t.Fatalf("expected no providers without OTel config, got %+v", status.Providers)
	}
	if !status.Fallback.Logs || !status.Fallback.Traces || !status.Fallback.Metrics {
		t.Fatalf("expected fallback mode without OTel config, got %+v", status.Fallback)
	}
	if _, ok := telemetry.DefaultTracer.(_otelTracerAdapter); ok {
		t.Fatalf("expected fallback tracer without OTel config, got %T", telemetry.DefaultTracer)
	}
}

func TestOTel_TraceEndpointAutoWiresTracerProvider(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://collector:4318")

	if _, err := telemetry.SetupTelemetry(); err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	if _, ok := telemetry.DefaultTracer.(_otelTracerAdapter); !ok {
		t.Fatalf("expected env-configured traces endpoint to install OTel tracer, got %T", telemetry.DefaultTracer)
	}
	if _otelTracerProvider == nil {
		t.Fatal("expected env-configured traces endpoint to install tracer provider")
	}
}

func TestOTel_WithMeterProvider_WiresRealMeter(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	mp := sdkmetric.NewMeterProvider()
	if _, err := telemetry.SetupTelemetry(telemetry.WithMeterProvider(mp)); err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	if _otelMeterProvider == nil {
		t.Fatal("expected OTel meter provider to be installed")
	}
	if telemetry.GetMeter("otel.test") == nil {
		t.Fatal("expected GetMeter to return provider-backed meter")
	}
}

func TestOTel_LogsEndpointAutoWiresLoggerProvider(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "http://collector:4318")

	if _, err := telemetry.SetupTelemetry(); err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	if _otelLoggerProvider == nil {
		t.Fatal("expected logger provider to be installed")
	}
	if got := logglobal.GetLoggerProvider(); got == nil {
		t.Fatal("expected global logger provider to be set")
	}
}

func TestOTel_InvalidSharedEndpointDegradesWithoutInstallingProviders(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://[")

	if _, err := telemetry.SetupTelemetry(); err != nil {
		t.Fatalf("SetupTelemetry should fail open on invalid endpoint, got %v", err)
	}

	status := telemetry.GetRuntimeStatus()
	if status.Providers.Logs || status.Providers.Traces || status.Providers.Metrics {
		t.Fatalf("expected no providers after fail-open init, got %+v", status.Providers)
	}
	if !status.Fallback.Logs || !status.Fallback.Traces || !status.Fallback.Metrics {
		t.Fatalf("expected fallback mode after fail-open init, got %+v", status.Fallback)
	}
}

func TestOTel_GetLogger_EmitsThroughLoggerProvider(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	exporter := &_inMemoryLogExporter{}
	lp := sdklog.NewLoggerProvider(sdklog.WithProcessor(sdklog.NewSimpleProcessor(exporter)))

	if _, err := telemetry.SetupTelemetry(telemetry.WithLoggerProvider(lp)); err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	telemetry.GetLogger(context.Background(), "integration.bridge").Info("otel facade logger bridge")

	if err := telemetry.ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("ShutdownTelemetry failed: %v", err)
	}

	bodies := exporter.bodies()
	if len(bodies) == 0 {
		t.Fatal("expected log output to be exported through the OTel bridge")
	}
}

func TestOTel_NewCounter_RecordsThroughMeterProvider(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	reader := sdkmetric.NewManualReader()
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader))

	if _, err := telemetry.SetupTelemetry(telemetry.WithMeterProvider(mp)); err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	telemetry.NewCounter("otel.facade.counter", telemetry.WithDescription("facade counter"), telemetry.WithUnit("1")).
		Add(context.Background(), 5)

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

func TestOTel_ShutdownTelemetry_ClearsProvidersAndRestoresFallback(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	tp, _ := newInMemoryTP()
	mp := sdkmetric.NewMeterProvider()
	lp := sdklog.NewLoggerProvider()

	if _, err := telemetry.SetupTelemetry(
		telemetry.WithTracerProvider(tp),
		telemetry.WithMeterProvider(mp),
		telemetry.WithLoggerProvider(lp),
	); err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	if err := telemetry.ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("ShutdownTelemetry failed: %v", err)
	}

	if _otelTracerProvider != nil || _otelMeterProvider != nil || _otelLoggerProvider != nil {
		t.Fatalf("expected providers to be cleared after shutdown")
	}
	if _, ok := otel.GetTracerProvider().(otelnooptrace.TracerProvider); !ok {
		t.Fatalf("expected global tracer provider to reset to noop, got %T", otel.GetTracerProvider())
	}
	if _, ok := otel.GetMeterProvider().(otelmetricnoop.MeterProvider); !ok {
		t.Fatalf("expected global meter provider to reset to noop, got %T", otel.GetMeterProvider())
	}
	if _, ok := logglobal.GetLoggerProvider().(*sdklog.LoggerProvider); ok {
		t.Fatalf("expected global logger provider to reset away from SDK logger, got %T", logglobal.GetLoggerProvider())
	}
	status := telemetry.GetRuntimeStatus()
	if !status.Fallback.Logs || !status.Fallback.Traces || !status.Fallback.Metrics {
		t.Fatalf("expected fallback mode after shutdown, got %+v", status.Fallback)
	}
}
