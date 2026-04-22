// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"testing"

	telemetry "github.com/provide-io/provide-telemetry/go"
	"go.opentelemetry.io/otel"
	logglobal "go.opentelemetry.io/otel/log/global"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
)

func TestCoverageLowLevel_BackendAccessorsWithoutProviders(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	backend := &_backend{}
	if backend.Tracer("coverage") != nil {
		t.Fatal("expected nil tracer when no tracer provider is installed")
	}
	if backend.LoggerHandler("coverage") != nil {
		t.Fatal("expected nil logger handler when no logger provider is installed")
	}
	if backend.Meter("coverage") != nil {
		t.Fatal("expected nil meter when no meter provider is installed")
	}
	if counter, ok := backend.NewCounter("coverage.counter", telemetry.InstrumentOptions{}); ok || counter != nil {
		t.Fatalf("expected no counter without provider, got counter=%v ok=%v", counter, ok)
	}
	if gauge, ok := backend.NewGauge("coverage.gauge", telemetry.InstrumentOptions{}); ok || gauge != nil {
		t.Fatalf("expected no gauge without provider, got gauge=%v ok=%v", gauge, ok)
	}
	if histogram, ok := backend.NewHistogram("coverage.histogram", telemetry.InstrumentOptions{}); ok || histogram != nil {
		t.Fatalf("expected no histogram without provider, got histogram=%v ok=%v", histogram, ok)
	}
	if err := backend.Shutdown(context.Background()); err != nil {
		t.Fatalf("expected shutdown with no providers to succeed, got %v", err)
	}
}

func TestCoverageLowLevel_BackendAdaptersAndMetricWrappers(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	tp, exp := newInMemoryTP()
	reader := sdkmetric.NewManualReader()
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader))
	lp := sdklog.NewLoggerProvider()

	_otelTracerProvider = tp
	_otelMeterProvider = mp
	_otelLoggerProvider = lp

	backend := &_backend{}
	tracer := backend.Tracer("coverage.backend")
	if tracer == nil {
		t.Fatal("expected tracer when provider is installed")
	}
	ctx, span := tracer.Start(context.Background(), "coverage.backend.span")
	adapted := span.(*_otelSpanAdapter)
	adapted.SetAttribute("enabled", true)
	adapted.SetAttribute("count", 7)
	adapted.SetAttribute("total", int64(11))
	adapted.SetAttribute("latency", 1.25)
	adapted.SetAttribute("name", "alpha")
	adapted.SetAttribute("other", struct{ Field string }{Field: "value"})
	adapted.RecordError(errors.New("coverage failure"))
	if adapted.TraceID() == "" || adapted.SpanID() == "" {
		t.Fatalf("expected non-empty trace/span IDs, got %q/%q", adapted.TraceID(), adapted.SpanID())
	}
	traceID, spanID, ok := backend.TraceContext(ctx)
	if !ok || traceID == "" || spanID == "" {
		t.Fatalf("expected trace context from backend, got ok=%v trace=%q span=%q", ok, traceID, spanID)
	}
	adapted.End()

	spans := exp.GetSpans()
	if len(spans) != 1 {
		t.Fatalf("expected 1 exported span, got %d", len(spans))
	}

	if backend.LoggerHandler("coverage.logger") == nil {
		t.Fatal("expected logger handler when logger provider is installed")
	}
	if backend.Meter("coverage.meter") == nil {
		t.Fatal("expected meter when meter provider is installed")
	}

	counter, ok := backend.NewCounter("coverage.counter", telemetry.InstrumentOptions{Description: "counter", Unit: "1"})
	if !ok || counter == nil {
		t.Fatal("expected counter when meter provider is installed")
	}
	gauge, ok := backend.NewGauge("coverage.gauge", telemetry.InstrumentOptions{Description: "gauge", Unit: "ms"})
	if !ok || gauge == nil {
		t.Fatal("expected gauge when meter provider is installed")
	}
	histogram, ok := backend.NewHistogram("coverage.histogram", telemetry.InstrumentOptions{Description: "histogram", Unit: "ms"})
	if !ok || histogram == nil {
		t.Fatal("expected histogram when meter provider is installed")
	}

	counter.Add(ctx, 3, slog.String("kind", "counter"))
	gauge.Set(ctx, 2.5, slog.String("kind", "gauge"))
	histogram.Record(ctx, 4.5, slog.String("kind", "histogram"))

	var rm metricdata.ResourceMetrics
	if err := reader.Collect(context.Background(), &rm); err != nil {
		t.Fatalf("metric collect failed: %v", err)
	}

	seen := map[string]bool{}
	for _, scopeMetrics := range rm.ScopeMetrics {
		for _, metric := range scopeMetrics.Metrics {
			seen[metric.Name] = true
		}
	}
	for _, name := range []string{"coverage.counter", "coverage.gauge", "coverage.histogram"} {
		if !seen[name] {
			t.Fatalf("expected collected metric %q, saw %v", name, seen)
		}
	}

	if _recordOptions(nil) != nil {
		t.Fatal("expected nil record options when no attrs are supplied")
	}
}

func TestCoverageLowLevel_ConfigAndProviderHelpers(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	cfg := telemetry.DefaultTelemetryConfig()
	cfg.Metrics.OTLPEndpoint = "http://collector:4318"

	mp, err := _buildDefaultMeterProvider(cfg)
	if err != nil {
		t.Fatalf("expected meter provider build to succeed, got %v", err)
	}
	if err := mp.Shutdown(context.Background()); err != nil {
		t.Fatalf("expected built meter provider to shut down cleanly, got %v", err)
	}

	if _, err := _validatedSignalEndpointURL("", "/v1/metrics"); err == nil {
		t.Fatal("expected blank endpoint to fail validation")
	}
	if _, err := _validatedSignalEndpointURL("collector:4318", "/v1/metrics"); err == nil {
		t.Fatal("expected host without scheme to fail validation")
	}
	if _, err := _validatedSignalEndpointURL("ftp://collector:4318", "/v1/metrics"); err == nil {
		t.Fatal("expected invalid scheme to fail validation")
	}

	attr := _attributeFromSlogAttr(slog.Any("payload", map[string]int{"count": 1}))
	if got := fmt.Sprint(attr.Value.AsInterface()); got == "" {
		t.Fatal("expected fallback attribute conversion to string-format the value")
	}

	_setupMeterProvider(telemetry.BackendSetupState{}, cfg)
	if _otelMeterProvider == nil {
		t.Fatal("expected setupMeterProvider to build and install a meter provider from config")
	}
	if err := (&_backend{}).Shutdown(context.Background()); err != nil {
		t.Fatalf("expected cleanup shutdown to succeed, got %v", err)
	}

	cfg.Metrics.OTLPEndpoint = "http://["
	_setupMeterProvider(telemetry.BackendSetupState{}, cfg)
	if _otelMeterProvider != nil {
		t.Fatal("expected invalid endpoint to leave meter provider unset")
	}
}

func TestCoverageLowLevel_ConflictWarningsWithNilLogger(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() {
		resetOTelGlobal(t)
		resetSetupState(t)
	})

	prevLogger := telemetry.Logger
	telemetry.Logger = nil
	t.Cleanup(func() { telemetry.Logger = prevLogger })

	otel.SetTracerProvider(&_thirdPartyTracerProvider{})
	otel.SetMeterProvider(&_thirdPartyMeterProvider{})
	logglobal.SetLoggerProvider(&_thirdPartyLoggerProvider{})

	_warnIfTracerProviderConflict()
	_warnIfMeterProviderConflict()
	_warnIfLoggerProviderConflict()
}

func TestCoverageLowLevel_WarnIfMeterAndLoggerProviderConflict_NoWarnForOwnSDKProviders(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() {
		resetOTelGlobal(t)
		resetSetupState(t)
	})

	h := newCaptureHandler(slog.LevelWarn)
	telemetry.Logger = slog.New(h)

	mp := sdkmetric.NewMeterProvider()
	t.Cleanup(func() { _ = mp.Shutdown(context.Background()) })
	otel.SetMeterProvider(mp)
	_warnIfMeterProviderConflict()

	lp := sdklog.NewLoggerProvider()
	t.Cleanup(func() { _ = lp.Shutdown(context.Background()) })
	logglobal.SetLoggerProvider(lp)
	_warnIfLoggerProviderConflict()

	if h.buf.Len() != 0 {
		t.Fatalf("expected no conflict warning for SDK-owned providers, got %q", h.buf.String())
	}
}

func TestCoverageLowLevel_SetupMeterProviderNoopAndInstrumentCreationErrors(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	backend := &_backend{}
	cfg := telemetry.DefaultTelemetryConfig()

	_setupMeterProvider(telemetry.BackendSetupState{}, cfg)
	if _otelMeterProvider != nil {
		t.Fatal("expected no meter provider to be installed without config or provider")
	}

	reader := sdkmetric.NewManualReader()
	_otelMeterProvider = sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader))

	if counter, ok := backend.NewCounter("", telemetry.InstrumentOptions{}); ok || counter != nil {
		t.Fatalf("expected empty-name counter creation to fail, got counter=%v ok=%v", counter, ok)
	}
	if gauge, ok := backend.NewGauge("", telemetry.InstrumentOptions{}); ok || gauge != nil {
		t.Fatalf("expected empty-name gauge creation to fail, got gauge=%v ok=%v", gauge, ok)
	}
	if histogram, ok := backend.NewHistogram("", telemetry.InstrumentOptions{}); ok || histogram != nil {
		t.Fatalf("expected empty-name histogram creation to fail, got histogram=%v ok=%v", histogram, ok)
	}
}

func TestCoverageLowLevel_SetupTelemetryWrongMeterProviderIgnored(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := telemetry.SetupTelemetry(telemetry.WithMeterProvider(struct{}{})); err != nil {
		t.Fatalf("expected wrong-type meter provider to be ignored, got %v", err)
	}
	if _otelMeterProvider != nil {
		t.Fatal("expected wrong-type meter provider to be ignored")
	}
}

func TestCoverageLowLevel_BackendShutdownPreservesFirstError(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	tp, _ := newInMemoryTP()
	mp := sdkmetric.NewMeterProvider()
	lp := sdklog.NewLoggerProvider(
		sdklog.WithProcessor(sdklog.NewSimpleProcessor(&_erroringLogExporter{shutdownErr: errors.New("logger shutdown failed")})),
	)

	_otelTracerProvider = tp
	_otelMeterProvider = mp
	_otelLoggerProvider = lp

	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	if err := (&_backend{}).Shutdown(ctx); err == nil {
		t.Fatal("expected shutdown with canceled context to surface an error")
	}
	if _otelTracerProvider != nil || _otelMeterProvider != nil || _otelLoggerProvider != nil {
		t.Fatal("expected shutdown to clear all provider pointers even when errors occur")
	}
}

func TestCoverageLowLevel_BackendShutdownSurfacesMeterError(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	mp := sdkmetric.NewMeterProvider()
	_ = mp.Shutdown(context.Background())
	_otelMeterProvider = mp

	if err := (&_backend{}).Shutdown(context.Background()); err == nil {
		t.Fatal("expected second meter shutdown to surface an error")
	}
}
