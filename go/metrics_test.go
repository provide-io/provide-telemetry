// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"sync"
	"testing"
	"log/slog"
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

func TestBackendBackedMeterAndInstrumentWrappers(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	_resetSamplingPolicies()
	_resetQueuePolicy()
	t.Cleanup(_resetSamplingPolicies)
	t.Cleanup(_resetQueuePolicy)

	backend := &_fakeBackend{}
	RegisterBackend("fake", backend)
	t.Cleanup(func() { UnregisterBackend("fake") })
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	if got := GetMeter("backend.metrics"); got != "meter:backend.metrics" {
		t.Fatalf("expected backend meter, got %v", got)
	}

	counter := NewCounter("backend.counter", WithDescription("provider counter"), WithUnit("1"))
	if _, ok := counter.(*_backendCounter); !ok {
		t.Fatalf("expected backend counter wrapper, got %T", counter)
	}
	counter.Add(context.Background(), 2, slog.Bool("ok", true))

	gauge := NewGauge("backend.gauge", WithDescription("provider gauge"), WithUnit("bytes"))
	if _, ok := gauge.(*_backendGauge); !ok {
		t.Fatalf("expected backend gauge wrapper, got %T", gauge)
	}
	gauge.Set(context.Background(), 12.5, slog.String("kind", "gauge"))

	histogram := NewHistogram("backend.histogram", WithDescription("provider histogram"), WithUnit("ms"))
	if _, ok := histogram.(*_backendHistogram); !ok {
		t.Fatalf("expected backend histogram wrapper, got %T", histogram)
	}
	histogram.Record(context.Background(), 4.2, slog.Int("status", 200))

	if len(backend.counterAdds) != 1 || backend.counterAdds[0] != 2 {
		t.Fatalf("expected backend counter add to be recorded, got %v", backend.counterAdds)
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

	backend := &_fakeBackend{}
	RegisterBackend("fake", backend)
	t.Cleanup(func() { UnregisterBackend("fake") })
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	counter := NewCounter("backend.counter.gate")
	gauge := NewGauge("backend.gauge.gate")
	histogram := NewHistogram("backend.hist.gate")
	if _, ok := counter.(*_backendCounter); !ok {
		t.Fatalf("expected backend-backed counter, got %T", counter)
	}
	if _, ok := gauge.(*_backendGauge); !ok {
		t.Fatalf("expected backend-backed gauge, got %T", gauge)
	}
	if _, ok := histogram.(*_backendHistogram); !ok {
		t.Fatalf("expected backend-backed histogram, got %T", histogram)
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
		t.Fatalf("expected backend-backed metrics to respect sampling gate: before=%d after=%d", before.MetricsEmitted, after.MetricsEmitted)
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
		t.Fatalf("expected backend-backed metrics to respect backpressure gate: before=%d after=%d", before.MetricsEmitted, after.MetricsEmitted)
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
