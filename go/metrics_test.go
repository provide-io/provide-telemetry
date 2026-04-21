// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"log/slog"
	"math"
	"sync"
	"testing"
)

func TestNewCounterNonNil(t *testing.T) {
	c := NewCounter("test.counter")
	if c == nil {
		t.Fatal("expected non-nil Counter")
	}
}

func TestCounterAdd(t *testing.T) {
	_resetSamplingPolicies()
	_resetQueuePolicy()

	c := NewCounter("test.add")
	ac, ok := c.(*_atomicCounter)
	if !ok {
		t.Fatal("expected *_atomicCounter")
	}
	c.Add(context.Background(), 5)
	if got := ac.Value(); got != 5 {
		t.Fatalf("expected 5, got %d", got)
	}
}

func TestCounterAddDropsWhenSamplingZero(t *testing.T) {
	_resetSamplingPolicies()
	_resetQueuePolicy()
	if _, err := SetSamplingPolicy(signalMetrics, SamplingPolicy{DefaultRate: 0.0}); err != nil {
		t.Fatal(err)
	}
	defer _resetSamplingPolicies()

	c := NewCounter("test.sample.drop")
	ac := c.(*_atomicCounter)
	c.Add(context.Background(), 10)
	if got := ac.Value(); got != 0 {
		t.Fatalf("expected 0, got %d", got)
	}
}

func TestCounterAddDropsWhenBackpressureAtCapacity(t *testing.T) {
	_resetSamplingPolicies()
	SetQueuePolicy(QueuePolicy{LogsMaxSize: 1, TracesMaxSize: 1, MetricsMaxSize: 1})
	defer _resetQueuePolicy()

	// fill the queue
	TryAcquire(signalMetrics)

	c := NewCounter("test.bp.drop")
	ac := c.(*_atomicCounter)
	c.Add(context.Background(), 7)
	if got := ac.Value(); got != 0 {
		t.Fatalf("expected 0, got %d", got)
	}
}

func TestNewGaugeNonNil(t *testing.T) {
	g := NewGauge("test.gauge")
	if g == nil {
		t.Fatal("expected non-nil Gauge")
	}
}

func TestGaugeSet(t *testing.T) {
	_resetSamplingPolicies()
	_resetQueuePolicy()

	g := NewGauge("test.gauge.set")
	ag := g.(*_atomicGauge)
	g.Set(context.Background(), 3.14)
	if got := ag.Value(); got != 3.14 {
		t.Fatalf("expected 3.14, got %f", got)
	}
}

func TestGaugeSetDropsWhenSamplingZero(t *testing.T) {
	_resetSamplingPolicies()
	_resetQueuePolicy()
	if _, err := SetSamplingPolicy(signalMetrics, SamplingPolicy{DefaultRate: 0.0}); err != nil {
		t.Fatal(err)
	}
	defer _resetSamplingPolicies()

	g := NewGauge("test.gauge.sample.drop")
	ag := g.(*_atomicGauge)
	g.Set(context.Background(), 99.9)
	if got := ag.Value(); got != 0.0 {
		t.Fatalf("expected 0, got %f", got)
	}
}

func TestGaugeSetDropsWhenBackpressureAtCapacity(t *testing.T) {
	_resetSamplingPolicies()
	SetQueuePolicy(QueuePolicy{LogsMaxSize: 1, TracesMaxSize: 1, MetricsMaxSize: 1})
	defer _resetQueuePolicy()

	// fill the queue
	TryAcquire(signalMetrics)

	g := NewGauge("test.gauge.bp.drop")
	ag := g.(*_atomicGauge)
	g.Set(context.Background(), 55.5)
	if got := ag.Value(); got != 0.0 {
		t.Fatalf("expected 0, got %f", got)
	}
}

func TestNewHistogramNonNil(t *testing.T) {
	h := NewHistogram("test.histogram")
	if h == nil {
		t.Fatal("expected non-nil Histogram")
	}
}

func TestHistogramRecord(t *testing.T) {
	_resetSamplingPolicies()
	_resetQueuePolicy()

	h := NewHistogram("test.hist.record")
	ah := h.(*_atomicHistogram)
	h.Record(context.Background(), 2.5)
	h.Record(context.Background(), 7.5)
	if got := ah.Count(); got != 2 {
		t.Fatalf("expected count 2, got %d", got)
	}
	if got := ah.Sum(); got != 10.0 {
		t.Fatalf("expected sum 10.0, got %f", got)
	}
}

func TestHistogramRecordDropsWhenSamplingZero(t *testing.T) {
	_resetSamplingPolicies()
	_resetQueuePolicy()
	if _, err := SetSamplingPolicy(signalMetrics, SamplingPolicy{DefaultRate: 0.0}); err != nil {
		t.Fatal(err)
	}
	defer _resetSamplingPolicies()

	h := NewHistogram("test.hist.sample.drop")
	ah := h.(*_atomicHistogram)
	h.Record(context.Background(), 42.0)
	if got := ah.Count(); got != 0 {
		t.Fatalf("expected count 0, got %d", got)
	}
	if got := ah.Sum(); got != 0.0 {
		t.Fatalf("expected sum 0.0, got %f", got)
	}
}

func TestHistogramRecordDropsWhenBackpressureAtCapacity(t *testing.T) {
	_resetSamplingPolicies()
	SetQueuePolicy(QueuePolicy{LogsMaxSize: 1, TracesMaxSize: 1, MetricsMaxSize: 1})
	defer _resetQueuePolicy()

	// fill the queue
	TryAcquire(signalMetrics)

	h := NewHistogram("test.hist.bp.drop")
	ah := h.(*_atomicHistogram)
	h.Record(context.Background(), 1.0)
	if got := ah.Count(); got != 0 {
		t.Fatalf("expected count 0, got %d", got)
	}
}

func TestGetMeterReturnsNil(t *testing.T) {
	if m := GetMeter("test.meter"); m != nil {
		t.Fatalf("expected nil, got %v", m)
	}
}

func TestGetMeterAutoWiredFromEndpoint(t *testing.T) {
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
	defer _resetSetup()
	defer _resetOTelProviders()

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("SetupTelemetry: %v", err)
	}

	m := GetMeter("test.auto.meter")
	if m == nil {
		t.Fatal("expected non-nil Meter when OTEL_EXPORTER_OTLP_ENDPOINT is set")
	}
}

func TestOptionsAccepted(t *testing.T) {
	c := NewCounter("test.opts", WithDescription("a counter"), WithUnit("requests"))
	if c == nil {
		t.Fatal("expected non-nil Counter with options")
	}
	g := NewGauge("test.opts.gauge", WithDescription("a gauge"), WithUnit("bytes"))
	if g == nil {
		t.Fatal("expected non-nil Gauge with options")
	}
	h := NewHistogram("test.opts.hist", WithDescription("a histogram"), WithUnit("ms"))
	if h == nil {
		t.Fatal("expected non-nil Histogram with options")
	}
}

func TestProviderBackedMetricsAndOptionHelpers(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	_resetSamplingPolicies()
	_resetQueuePolicy()
	t.Cleanup(_resetSamplingPolicies)
	t.Cleanup(_resetQueuePolicy)

	mp := sdkmetric.NewMeterProvider()
	if _, err := SetupTelemetry(WithMeterProvider(mp)); err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	counter := NewCounter("otel.counter.attrs", WithDescription("provider counter"), WithUnit("1"))
	if _, ok := counter.(*_otelCounter); !ok {
		t.Fatalf("expected provider-backed counter, got %T", counter)
	}
	counter.Add(context.Background(), 2, slog.Bool("ok", true))

	gauge := NewGauge("otel.gauge.attrs", WithDescription("provider gauge"), WithUnit("bytes"))
	if _, ok := gauge.(*_otelGauge); !ok {
		t.Fatalf("expected provider-backed gauge, got %T", gauge)
	}
	gauge.Set(context.Background(), 12.5, slog.String("kind", "gauge"))

	histogram := NewHistogram("otel.hist.attrs", WithDescription("provider histogram"), WithUnit("ms"))
	if _, ok := histogram.(*_otelHistogram); !ok {
		t.Fatalf("expected provider-backed histogram, got %T", histogram)
	}
	histogram.Record(context.Background(), 4.2, slog.Int("status", 200))

	opts := _applyOptions([]Option{WithDescription("desc"), WithUnit("ms")})
	if got := _gaugeOptions(opts); len(got) != 2 {
		t.Fatalf("expected gauge options to include description and unit, got %d", len(got))
	}
	if got := _histogramOptions(opts); len(got) != 2 {
		t.Fatalf("expected histogram options to include description and unit, got %d", len(got))
	}
	if got := _addOptions(nil); got != nil {
		t.Fatalf("expected nil add options for empty attrs, got %v", got)
	}
	if got := _recordOptions(nil); got != nil {
		t.Fatalf("expected nil record options for empty attrs, got %v", got)
	}
	if got := _addOptions([]slog.Attr{slog.String("env", "test")}); len(got) != 1 {
		t.Fatalf("expected one add option for attrs, got %d", len(got))
	}
	if got := _recordOptions([]slog.Attr{slog.String("env", "test")}); len(got) != 1 {
		t.Fatalf("expected one record option for attrs, got %d", len(got))
	}
}

func setupProviderBackedMetricsForGate(t *testing.T) (Counter, Gauge, Histogram) {
	t.Helper()
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	_resetSamplingPolicies()
	_resetQueuePolicy()
	_resetHealth()
	t.Cleanup(_resetSamplingPolicies)
	t.Cleanup(_resetQueuePolicy)
	t.Cleanup(_resetHealth)

	mp := sdkmetric.NewMeterProvider()
	if _, err := SetupTelemetry(WithMeterProvider(mp)); err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	counter := NewCounter("otel.counter.gate")
	gauge := NewGauge("otel.gauge.gate")
	histogram := NewHistogram("otel.hist.gate")
	if _, ok := counter.(*_otelCounter); !ok {
		t.Fatalf("expected provider-backed counter, got %T", counter)
	}
	if _, ok := gauge.(*_otelGauge); !ok {
		t.Fatalf("expected provider-backed gauge, got %T", gauge)
	}
	if _, ok := histogram.(*_otelHistogram); !ok {
		t.Fatalf("expected provider-backed histogram, got %T", histogram)
	}
	return counter, gauge, histogram
}

func TestProviderBackedMetricsRespectSampling(t *testing.T) {
	counter, gauge, histogram := setupProviderBackedMetricsForGate(t)
	if _, err := SetSamplingPolicy(signalMetrics, SamplingPolicy{DefaultRate: 0.0}); err != nil {
		t.Fatalf("SetSamplingPolicy failed: %v", err)
	}

	before := GetHealthSnapshot()
	counter.Add(context.Background(), 1)
	gauge.Set(context.Background(), 2.5)
	histogram.Record(context.Background(), 3.5)
	after := GetHealthSnapshot()

	if after.MetricsEmitted != before.MetricsEmitted {
		t.Fatalf("expected provider-backed metrics to respect sampling gate: before=%d after=%d", before.MetricsEmitted, after.MetricsEmitted)
	}
}

func TestProviderBackedMetricsRespectBackpressure(t *testing.T) {
	counter, gauge, histogram := setupProviderBackedMetricsForGate(t)
	SetQueuePolicy(QueuePolicy{LogsMaxSize: 1, TracesMaxSize: 1, MetricsMaxSize: 1})
	if !TryAcquire(signalMetrics) {
		t.Fatal("expected initial acquire to fill the metrics queue")
	}

	before := GetHealthSnapshot()
	counter.Add(context.Background(), 1)
	gauge.Set(context.Background(), 2.5)
	histogram.Record(context.Background(), 3.5)
	after := GetHealthSnapshot()

	if after.MetricsEmitted != before.MetricsEmitted {
		t.Fatalf("expected provider-backed metrics to respect backpressure gate: before=%d after=%d", before.MetricsEmitted, after.MetricsEmitted)
	}
}

func TestAttributeFromSlogAttr_ConvertsSupportedKinds(t *testing.T) {
	now := time.Date(2026, time.April, 17, 12, 0, 0, 0, time.UTC)

	cases := []struct {
		assertion func(t *testing.T)
	}{
		{
			assertion: func(t *testing.T) {
				kv := _attributeFromSlogAttr(slog.Bool("ok", true))
				if kv.Key != "ok" || !kv.Value.AsBool() {
					t.Fatalf("unexpected bool conversion: %+v", kv)
				}
			},
		},
		{
			assertion: func(t *testing.T) {
				kv := _attributeFromSlogAttr(slog.Duration("latency", 3*time.Second))
				if kv.Key != "latency" || kv.Value.AsString() != "3s" {
					t.Fatalf("unexpected duration conversion: %+v", kv)
				}
			},
		},
		{
			assertion: func(t *testing.T) {
				kv := _attributeFromSlogAttr(slog.Float64("ratio", 1.5))
				if kv.Key != "ratio" || kv.Value.AsFloat64() != 1.5 {
					t.Fatalf("unexpected float conversion: %+v", kv)
				}
			},
		},
		{
			assertion: func(t *testing.T) {
				kv := _attributeFromSlogAttr(slog.Int64("count", 7))
				if kv.Key != "count" || kv.Value.AsInt64() != 7 {
					t.Fatalf("unexpected int conversion: %+v", kv)
				}
			},
		},
		{
			assertion: func(t *testing.T) {
				kv := _attributeFromSlogAttr(slog.String("service", "api"))
				if kv.Key != "service" || kv.Value.AsString() != "api" {
					t.Fatalf("unexpected string conversion: %+v", kv)
				}
			},
		},
		{
			assertion: func(t *testing.T) {
				kv := _attributeFromSlogAttr(slog.Time("at", now))
				if kv.Key != "at" || kv.Value.AsString() != now.Format("2006-01-02T15:04:05.999999999Z07:00") {
					t.Fatalf("unexpected time conversion: %+v", kv)
				}
			},
		},
		{
			assertion: func(t *testing.T) {
				kv := _attributeFromSlogAttr(slog.Uint64("bytes", 9))
				if kv.Key != "bytes" || kv.Value.AsInt64() != 9 {
					t.Fatalf("unexpected uint64 conversion: %+v", kv)
				}
			},
		},
		{
			assertion: func(t *testing.T) {
				kv := _attributeFromSlogAttr(slog.Uint64("bytes", uint64(math.MaxInt64)+1))
				if kv.Key != "bytes" || kv.Value.AsString() != "9223372036854775808" {
					t.Fatalf("unexpected uint64 overflow conversion: %+v", kv)
				}
			},
		},
		{
			assertion: func(t *testing.T) {
				kv := _attributeFromSlogAttr(slog.Group("ctx", slog.String("env", "test")))
				if kv.Key != "ctx" || kv.Value.AsString() != "[env=test]" {
					t.Fatalf("unexpected group conversion: %+v", kv)
				}
			},
		},
		{
			assertion: func(t *testing.T) {
				kv := _attributeFromSlogAttr(slog.Any("meta", map[string]int{"a": 1}))
				if kv.Key != "meta" || kv.Value.AsString() != "map[a:1]" {
					t.Fatalf("unexpected fallback conversion: %+v", kv)
				}
			},
		},
	}

	for _, tc := range cases {
		tc.assertion(t)
	}
}

func TestCounterConcurrency(t *testing.T) {
	_resetSamplingPolicies()
	_resetQueuePolicy()

	c := NewCounter("test.concurrent")
	ac := c.(*_atomicCounter)

	const goroutines = 50
	const adds = 10
	var wg sync.WaitGroup
	wg.Add(goroutines)
	for i := 0; i < goroutines; i++ {
		go func() {
			defer wg.Done()
			for j := 0; j < adds; j++ {
				c.Add(context.Background(), 1, slog.String("k", "v"))
			}
		}()
	}
	wg.Wait()

	if got := ac.Value(); got != int64(goroutines*adds) {
		t.Fatalf("expected %d, got %d", goroutines*adds, got)
	}
}
