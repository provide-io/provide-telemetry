// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"fmt"
	"log/slog"
	"math"
	"sync/atomic"

	"go.opentelemetry.io/otel/attribute"
	otelmetric "go.opentelemetry.io/otel/metric"
)

// Option configures optional instrument metadata.
type Option func(*_instrumentOptions)

type _instrumentOptions struct {
	description string
	unit        string
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

type _otelCounter struct {
	name  string
	inner otelmetric.Int64Counter
}

type _otelGauge struct {
	name  string
	inner otelmetric.Float64Gauge
}

type _otelHistogram struct {
	name  string
	inner otelmetric.Float64Histogram
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
	_setupMu.Lock()
	meterProvider := _otelMeterProvider
	_setupMu.Unlock()
	if meterProvider != nil {
		meter := meterProvider.Meter("provide.telemetry")
		counter, err := meter.Int64Counter(name, _counterOptions(applied)...)
		if err == nil {
			return &_otelCounter{name: name, inner: counter}
		}
	}
	return &_atomicCounter{name: name}
}

// NewGauge creates a named Gauge with in-process atomic fallback.
func NewGauge(name string, opts ...Option) Gauge {
	applied := _applyOptions(opts)
	_setupMu.Lock()
	meterProvider := _otelMeterProvider
	_setupMu.Unlock()
	if meterProvider != nil {
		meter := meterProvider.Meter("provide.telemetry")
		gauge, err := meter.Float64Gauge(name, _gaugeOptions(applied)...)
		if err == nil {
			return &_otelGauge{name: name, inner: gauge}
		}
	}
	return &_atomicGauge{name: name}
}

// NewHistogram creates a named Histogram with in-process atomic fallback.
func NewHistogram(name string, opts ...Option) Histogram {
	applied := _applyOptions(opts)
	_setupMu.Lock()
	meterProvider := _otelMeterProvider
	_setupMu.Unlock()
	if meterProvider != nil {
		meter := meterProvider.Meter("provide.telemetry")
		histogram, err := meter.Float64Histogram(name, _histogramOptions(applied)...)
		if err == nil {
			return &_otelHistogram{name: name, inner: histogram}
		}
	}
	return &_atomicHistogram{name: name}
}

// GetMeter returns a named OTel metric.Meter when an OTel MeterProvider has been
// installed — either automatically when OTEL_EXPORTER_OTLP_ENDPOINT is set and
// SetupTelemetry is called, or explicitly via SetupTelemetry(WithMeterProvider(mp)).
// Returns nil if no provider has been wired.
func GetMeter(name string) any {
	_setupMu.Lock()
	meterProvider := _otelMeterProvider
	_setupMu.Unlock()
	if meterProvider == nil {
		return nil
	}
	return meterProvider.Meter(name)
}

func (c *_otelCounter) Add(ctx context.Context, value int64, attrs ...slog.Attr) {
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
	c.inner.Add(ctx, value, _addOptions(attrs)...)
	_incMetricsRecorded()
}

func (g *_otelGauge) Set(ctx context.Context, value float64, attrs ...slog.Attr) {
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
	// OTel Float64Gauge uses Record (not Set) per the OTel Go API convention.
	g.inner.Record(ctx, value, _recordOptions(attrs)...)
	_incMetricsRecorded()
}

func (h *_otelHistogram) Record(ctx context.Context, value float64, attrs ...slog.Attr) {
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
	h.inner.Record(ctx, value, _recordOptions(attrs)...)
	_incMetricsRecorded()
}

func _counterOptions(opts *_instrumentOptions) []otelmetric.Int64CounterOption {
	options := make([]otelmetric.Int64CounterOption, 0, 2)
	if opts.description != "" {
		options = append(options, otelmetric.WithDescription(opts.description))
	}
	if opts.unit != "" {
		options = append(options, otelmetric.WithUnit(opts.unit))
	}
	return options
}

func _gaugeOptions(opts *_instrumentOptions) []otelmetric.Float64GaugeOption {
	options := make([]otelmetric.Float64GaugeOption, 0, 2)
	if opts.description != "" {
		options = append(options, otelmetric.WithDescription(opts.description))
	}
	if opts.unit != "" {
		options = append(options, otelmetric.WithUnit(opts.unit))
	}
	return options
}

func _histogramOptions(opts *_instrumentOptions) []otelmetric.Float64HistogramOption {
	options := make([]otelmetric.Float64HistogramOption, 0, 2)
	if opts.description != "" {
		options = append(options, otelmetric.WithDescription(opts.description))
	}
	if opts.unit != "" {
		options = append(options, otelmetric.WithUnit(opts.unit))
	}
	return options
}

func _addOptions(attrs []slog.Attr) []otelmetric.AddOption {
	if len(attrs) == 0 {
		return nil
	}
	keyValues := make([]attribute.KeyValue, 0, len(attrs))
	for _, attr := range attrs {
		keyValues = append(keyValues, _attributeFromSlogAttr(attr))
	}
	return []otelmetric.AddOption{otelmetric.WithAttributes(keyValues...)}
}

func _recordOptions(attrs []slog.Attr) []otelmetric.RecordOption {
	if len(attrs) == 0 {
		return nil
	}
	keyValues := make([]attribute.KeyValue, 0, len(attrs))
	for _, attr := range attrs {
		keyValues = append(keyValues, _attributeFromSlogAttr(attr))
	}
	return []otelmetric.RecordOption{otelmetric.WithAttributes(keyValues...)}
}

func _attributeFromSlogAttr(attr slog.Attr) attribute.KeyValue {
	value := attr.Value.Resolve()
	switch value.Kind() {
	case slog.KindBool:
		return attribute.Bool(attr.Key, value.Bool())
	case slog.KindDuration:
		return attribute.String(attr.Key, value.Duration().String())
	case slog.KindFloat64:
		return attribute.Float64(attr.Key, value.Float64())
	case slog.KindInt64:
		return attribute.Int64(attr.Key, value.Int64())
	case slog.KindString:
		return attribute.String(attr.Key, value.String())
	case slog.KindTime:
		return attribute.String(attr.Key, value.Time().Format("2006-01-02T15:04:05.999999999Z07:00"))
	case slog.KindUint64:
		return attribute.Int64(attr.Key, int64(value.Uint64()))
	default:
		return attribute.String(attr.Key, fmt.Sprint(value.Any()))
	}
}
