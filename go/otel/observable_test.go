// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"strings"
	"testing"

	telemetry "github.com/provide-io/provide-telemetry/go"
	otelmetric "go.opentelemetry.io/otel/metric"
	"go.opentelemetry.io/otel/metric/noop"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
)

func _manualProvider(t *testing.T) *sdkmetric.ManualReader {
	t.Helper()
	_promReset(t)
	reader := sdkmetric.NewManualReader()
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader))
	t.Cleanup(func() { _ = mp.Shutdown(context.Background()) })
	_promSetup(t, telemetry.WithMeterProvider(mp))
	return reader
}

func _collect(t *testing.T, reader *sdkmetric.ManualReader) map[string]metricdata.Metrics {
	t.Helper()
	var rm metricdata.ResourceMetrics
	if err := reader.Collect(context.Background(), &rm); err != nil {
		t.Fatal(err)
	}
	out := map[string]metricdata.Metrics{}
	for _, sm := range rm.ScopeMetrics {
		for _, m := range sm.Metrics {
			out[m.Name] = m
		}
	}
	return out
}

func TestObservable_EachKindReachesTheProvider(t *testing.T) {
	reader := _manualProvider(t)
	calls := 0
	cb := func(context.Context) []telemetry.Observation {
		calls++
		return []telemetry.Observation{{Value: 3, Attrs: []slog.Attr{slog.String("core", "0")}}}
	}
	counter := telemetry.NewObservableCounter("obs.counter", cb, telemetry.WithUnit("s"), telemetry.WithDescription("cpu time"))
	telemetry.NewObservableGauge("obs.gauge", cb)
	telemetry.NewObservableUpDownCounter("obs.updown", cb)

	got := _collect(t, reader)
	sum, ok := got["obs.counter"].Data.(metricdata.Sum[float64])
	if !ok || !sum.IsMonotonic || sum.DataPoints[0].Value != 3 || got["obs.counter"].Unit != "s" || got["obs.counter"].Description != "cpu time" {
		t.Fatalf("counter = %+v", got["obs.counter"])
	}
	if v, _ := sum.DataPoints[0].Attributes.Value("core"); v.AsString() != "0" {
		t.Fatalf("attributes = %v", sum.DataPoints[0].Attributes)
	}
	if _, ok := got["obs.gauge"].Data.(metricdata.Gauge[float64]); !ok {
		t.Fatalf("gauge = %+v", got["obs.gauge"])
	}
	if s, ok := got["obs.updown"].Data.(metricdata.Sum[float64]); !ok || s.IsMonotonic {
		t.Fatalf("updown = %+v", got["obs.updown"])
	}

	before := calls
	counter.Unregister()
	_collect(t, reader)
	if calls-before != 2 { // the gauge and up-down callbacks still run; the counter's no longer does
		t.Fatalf("after unregister %d callbacks ran, want 2", calls-before)
	}
}

func TestObservable_ServedByPrometheusHandler(t *testing.T) {
	_promReset(t)
	t.Setenv("OTEL_METRICS_EXPORTER", "prometheus")
	_promSetup(t)
	telemetry.NewObservableGauge("device.temperature", func(context.Context) []telemetry.Observation {
		return []telemetry.Observation{{Value: 41.5}}
	}, telemetry.WithUnit("Cel"))
	body := _scrape(http.MethodGet).Body.String()
	if !strings.Contains(body, "device_temperature_celsius 41.5") {
		t.Fatalf("observable gauge not scraped:\n%s", body)
	}
}

func TestObservable_NoProviderRefuses(t *testing.T) {
	_promReset(t)
	if unregister, ok := (&_backend{}).NewObservable(telemetry.ObservableKindGauge, "g", telemetry.InstrumentOptions{}, nil); ok || unregister != nil {
		t.Fatal("without a provider NewObservable must refuse")
	}
}

func TestObservable_InvalidNameRefuses(t *testing.T) {
	meter := sdkmetric.NewMeterProvider().Meter("t")
	if _, ok := _registerObservable(meter, telemetry.ObservableKindCounter, "1bad", telemetry.InstrumentOptions{}, nil); ok {
		t.Fatal("an invalid instrument name must refuse")
	}
}

type _refusingMeter struct{ noop.Meter }

func (_refusingMeter) RegisterCallback(otelmetric.Callback, ...otelmetric.Observable) (otelmetric.Registration, error) {
	return nil, errors.New("refused")
}

func TestObservable_RegisterCallbackFailureRefuses(t *testing.T) {
	if _, ok := _registerObservable(_refusingMeter{}, telemetry.ObservableKindGauge, "g", telemetry.InstrumentOptions{}, nil); ok {
		t.Fatal("a RegisterCallback failure must refuse")
	}
}
