// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"log/slog"
	"math"
	"sync/atomic"
)

// Option configures optional instrument metadata.
type Option func(*_instrumentOptions)

type _instrumentOptions struct {
	description string
	unit        string
}

func (o *_instrumentOptions) snapshot() InstrumentOptions {
	if o == nil {
		return InstrumentOptions{}
	}
	return InstrumentOptions{
		Description: o.description,
		Unit:        o.unit,
	}
}

// WithDescription sets a human-readable description on the instrument.
func WithDescription(desc string) Option {
	return func(o *_instrumentOptions) { o.description = desc }
}

// WithUnit sets the unit label on the instrument.
func WithUnit(unit string) Option {
	return func(o *_instrumentOptions) { o.unit = unit }
}

// _applyOptions applies all Option functions to a fresh _instrumentOptions.
func _applyOptions(opts []Option) *_instrumentOptions {
	o := &_instrumentOptions{}
	for _, fn := range opts {
		fn(o)
	}
	return o
}

// Counter is a monotonically increasing integer instrument.
type Counter interface {
	Add(ctx context.Context, value int64, attrs ...slog.Attr)
}

// Gauge is a floating-point instrument that holds the last-written value.
type Gauge interface {
	Set(ctx context.Context, value float64, attrs ...slog.Attr)
}

// Histogram records individual observations and tracks count and sum.
type Histogram interface {
	Record(ctx context.Context, value float64, attrs ...slog.Attr)
}

type _backendCounter struct {
	name  string
	inner Counter
}

type _backendGauge struct {
	name  string
	inner Gauge
}

type _backendHistogram struct {
	name  string
	inner Histogram
}

// _atomicCounter is the in-process fallback Counter backed by atomic.Int64.
type _atomicCounter struct {
	name  string
	value atomic.Int64
}

// Add increments the counter by value, subject to consent, sampling and backpressure.
func (c *_atomicCounter) Add(ctx context.Context, value int64, attrs ...slog.Attr) {
	_ = ctx
	_ = attrs
	if !ShouldAllow(signalMetrics, "") {
		return
	}
	if sampled, _ := ShouldSample(signalMetrics, c.name); !sampled { // signalMetrics is a package-level constant; err is always nil
		return
	}
	if !TryAcquire(signalMetrics) {
		return
	}
	defer Release(signalMetrics)
	c.value.Add(value)
	_incMetricsRecorded()
}

// Value returns the current counter value.
func (c *_atomicCounter) Value() int64 { return c.value.Load() }

// _atomicGauge is the in-process fallback Gauge backed by atomic.Uint64 (float64 bits).
type _atomicGauge struct {
	name  string
	value atomic.Uint64
}

// Set stores value as the current gauge reading, subject to consent, sampling and backpressure.
func (g *_atomicGauge) Set(ctx context.Context, value float64, attrs ...slog.Attr) {
	_ = ctx
	_ = attrs
	if !ShouldAllow(signalMetrics, "") {
		return
	}
	if sampled, _ := ShouldSample(signalMetrics, g.name); !sampled { // signalMetrics is a package-level constant; err is always nil
		return
	}
	if !TryAcquire(signalMetrics) {
		return
	}
	defer Release(signalMetrics)
	g.value.Store(math.Float64bits(value))
	_incMetricsRecorded()
}

// Value returns the current gauge reading.
func (g *_atomicGauge) Value() float64 { return math.Float64frombits(g.value.Load()) }

// _atomicHistogram is the in-process fallback Histogram backed by atomic integers.
type _atomicHistogram struct {
	name  string
	count atomic.Int64
	sum   atomic.Uint64 // stores float64 bits
}

// Record adds a single observation, subject to consent, sampling and backpressure.
func (h *_atomicHistogram) Record(ctx context.Context, value float64, attrs ...slog.Attr) {
	_ = ctx
	_ = attrs
	if !ShouldAllow(signalMetrics, "") {
		return
	}
	if sampled, _ := ShouldSample(signalMetrics, h.name); !sampled { // signalMetrics is a package-level constant; err is always nil
		return
	}
	if !TryAcquire(signalMetrics) {
		return
	}
	defer Release(signalMetrics)
	h.count.Add(1)
	for {
		old := h.sum.Load()
		newVal := math.Float64bits(math.Float64frombits(old) + value)
		if h.sum.CompareAndSwap(old, newVal) {
			break
		}
	}
	_incMetricsRecorded()
}

// Count returns the number of observations recorded.
func (h *_atomicHistogram) Count() int64 { return h.count.Load() }

// Sum returns the running sum of all observed values.
func (h *_atomicHistogram) Sum() float64 { return math.Float64frombits(h.sum.Load()) }

// NewCounter creates a named Counter with in-process atomic fallback.
func NewCounter(name string, opts ...Option) Counter {
	applied := _applyOptions(opts)
	if backend := _activeBackend(); backend != nil {
		if counter, ok := backend.NewCounter(name, applied.snapshot()); ok && counter != nil {
			return &_backendCounter{name: name, inner: counter}
		}
	}
	return &_atomicCounter{name: name}
}

// NewGauge creates a named Gauge with in-process atomic fallback.
func NewGauge(name string, opts ...Option) Gauge {
	applied := _applyOptions(opts)
	if backend := _activeBackend(); backend != nil {
		if gauge, ok := backend.NewGauge(name, applied.snapshot()); ok && gauge != nil {
			return &_backendGauge{name: name, inner: gauge}
		}
	}
	return &_atomicGauge{name: name}
}

// NewHistogram creates a named Histogram with in-process atomic fallback.
func NewHistogram(name string, opts ...Option) Histogram {
	applied := _applyOptions(opts)
	if backend := _activeBackend(); backend != nil {
		if histogram, ok := backend.NewHistogram(name, applied.snapshot()); ok && histogram != nil {
			return &_backendHistogram{name: name, inner: histogram}
		}
	}
	return &_atomicHistogram{name: name}
}

// GetMeter returns a named backend meter when an optional provider backend has
// been installed. For the built-in OTel backend, import
// github.com/provide-io/provide-telemetry/go/otel and either rely on OTLP
// environment variables or call SetupTelemetry(WithMeterProvider(mp)).
// Returns nil if no provider backend has been wired.
func GetMeter(name string) any {
	if backend := _activeBackend(); backend != nil {
		return backend.Meter(name)
	}
	return nil
}

func (c *_backendCounter) Add(ctx context.Context, value int64, attrs ...slog.Attr) {
	if !ShouldAllow(signalMetrics, "") {
		return
	}
	if sampled, _ := ShouldSample(signalMetrics, c.name); !sampled {
		return
	}
	if !TryAcquire(signalMetrics) {
		return
	}
	defer Release(signalMetrics)
	c.inner.Add(ctx, value, attrs...)
	_incMetricsRecorded()
}

func (g *_backendGauge) Set(ctx context.Context, value float64, attrs ...slog.Attr) {
	if !ShouldAllow(signalMetrics, "") {
		return
	}
	if sampled, _ := ShouldSample(signalMetrics, g.name); !sampled {
		return
	}
	if !TryAcquire(signalMetrics) {
		return
	}
	defer Release(signalMetrics)
	g.inner.Set(ctx, value, attrs...)
	_incMetricsRecorded()
}

func (h *_backendHistogram) Record(ctx context.Context, value float64, attrs ...slog.Attr) {
	if !ShouldAllow(signalMetrics, "") {
		return
	}
	if sampled, _ := ShouldSample(signalMetrics, h.name); !sampled {
		return
	}
	if !TryAcquire(signalMetrics) {
		return
	}
	defer Release(signalMetrics)
	h.inner.Record(ctx, value, attrs...)
	_incMetricsRecorded()
}
