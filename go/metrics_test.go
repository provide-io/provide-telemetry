// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"log/slog"
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
