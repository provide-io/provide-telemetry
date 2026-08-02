// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"testing"

	telemetry "github.com/provide-io/provide-telemetry/go"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

// ForceFlush must drain every installed provider and leave all three installed
// — the drain half of Shutdown, which nils them out.
func TestBackendForceFlush_DrainsAndLeavesProvidersInstalled(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	tp, _ := newInMemoryTP()
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(sdkmetric.NewManualReader()))
	lp := sdklog.NewLoggerProvider()

	_otelTracerProvider = tp
	_otelMeterProvider = mp
	_otelLoggerProvider = lp

	backend := &_backend{}
	if err := backend.ForceFlush(context.Background()); err != nil {
		t.Fatalf("ForceFlush returned %v, want nil", err)
	}

	if _otelTracerProvider == nil || _otelMeterProvider == nil || _otelLoggerProvider == nil {
		t.Fatal("ForceFlush tore providers down; they must stay installed")
	}
	// Repeatable, because nothing was torn down.
	if err := backend.ForceFlush(context.Background()); err != nil {
		t.Fatalf("second ForceFlush returned %v, want nil", err)
	}
}

func TestBackendForceFlush_IsANoopWithNoProviders(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	_otelTracerProvider = nil
	_otelMeterProvider = nil
	_otelLoggerProvider = nil

	if err := (&_backend{}).ForceFlush(context.Background()); err != nil {
		t.Fatalf("ForceFlush with no providers returned %v, want nil", err)
	}
}

// ForceFlushBySignal must report one entry per signal this backend installed,
// and omit the rest. A signal absent from the map is what the facade turns into
// NotOwned — the answer for a provider a host application registered, which we
// deliberately never drain.
func TestBackendForceFlushBySignal_ReportsOnlyInstalledSignals(t *testing.T) {
	tp, _ := newInMemoryTP()
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(sdkmetric.NewManualReader()))
	lp := sdklog.NewLoggerProvider()

	cases := map[string]struct {
		tracer *sdktrace.TracerProvider
		meter  *sdkmetric.MeterProvider
		logger *sdklog.LoggerProvider
		want   []string
	}{
		"all three":    {tp, mp, lp, []string{telemetry.SignalTraces, telemetry.SignalMetrics, telemetry.SignalLogs}},
		"traces only":  {tp, nil, nil, []string{telemetry.SignalTraces}},
		"metrics only": {nil, mp, nil, []string{telemetry.SignalMetrics}},
		"logs only":    {nil, nil, lp, []string{telemetry.SignalLogs}},
		"none":         {nil, nil, nil, []string{}},
	}

	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			resetSetupState(t)
			t.Cleanup(func() { resetSetupState(t) })

			_otelTracerProvider = tc.tracer
			_otelMeterProvider = tc.meter
			_otelLoggerProvider = tc.logger

			results := (&_backend{}).ForceFlushBySignal(context.Background())

			if len(results) != len(tc.want) {
				t.Fatalf("got %d signals %v, want %d %v", len(results), results, len(tc.want), tc.want)
			}
			for _, signal := range tc.want {
				err, present := results[signal]
				if !present {
					t.Fatalf("signal %q missing from %v", signal, results)
				}
				if err != nil {
					t.Fatalf("signal %q drained with %v, want nil", signal, err)
				}
			}
			// Providers stay installed: this is a drain, not a teardown.
			if tc.tracer != nil && _otelTracerProvider == nil {
				t.Fatal("ForceFlushBySignal tore the tracer provider down")
			}
		})
	}
}

// A signal we did not install must be absent rather than reported as drained.
func TestBackendForceFlushBySignal_OmitsAnUninstalledSignal(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	tp, _ := newInMemoryTP()
	_otelTracerProvider = tp
	_otelMeterProvider = nil
	_otelLoggerProvider = nil

	results := (&_backend{}).ForceFlushBySignal(context.Background())

	if _, present := results[telemetry.SignalMetrics]; present {
		t.Fatalf("metrics must be absent when we installed no meter provider: %v", results)
	}
	if _, present := results[telemetry.SignalLogs]; present {
		t.Fatalf("logs must be absent when we installed no logger provider: %v", results)
	}
}
