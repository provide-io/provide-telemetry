// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
	"sync/atomic"
)

// Observation is one value an observable instrument's callback reports.
type Observation struct {
	Value float64
	Attrs []slog.Attr
}

// ObservableCallback reports an observable instrument's current observations.
// It runs at each collection: every scrape for Prometheus, every export
// interval for OTLP. A panic is recovered and that collection gets no
// observations from it.
type ObservableCallback func(ctx context.Context) []Observation

// ObservableCounter is a registered callback-reported monotonic counter.
type ObservableCounter interface {
	// Unregister stops the callback. Calling it again is a no-op.
	Unregister()
}

// ObservableGauge is a registered callback-reported gauge. A series the
// callback stops reporting disappears from the next collection.
type ObservableGauge interface {
	// Unregister stops the callback. Calling it again is a no-op.
	Unregister()
}

// ObservableUpDownCounter is a registered callback-reported non-monotonic sum.
type ObservableUpDownCounter interface {
	// Unregister stops the callback. Calling it again is a no-op.
	Unregister()
}

// ObservableKind selects the instrument an ObservableBackend creates.
type ObservableKind int

// Observable instrument kinds.
const (
	ObservableKindCounter ObservableKind = iota
	ObservableKindGauge
	ObservableKindUpDownCounter
)

// ObservableBackend is the optional half of Backend that supports observable
// instruments. It is separate from Backend so adding it does not break
// third-party Backend implementations; without it, observables never run.
type ObservableBackend interface {
	NewObservable(kind ObservableKind, name string, opts InstrumentOptions, callback ObservableCallback) (unregister func(), ok bool)
}

// NewObservableCounter registers callback as a monotonic counter. Like the
// synchronous instruments it binds to the provider live now, so call it after
// SetupTelemetry; without a provider the callback never runs.
func NewObservableCounter(name string, callback ObservableCallback, opts ...Option) ObservableCounter {
	return _newObservable(ObservableKindCounter, name, callback, opts)
}

// NewObservableGauge registers callback as a gauge; see NewObservableCounter.
func NewObservableGauge(name string, callback ObservableCallback, opts ...Option) ObservableGauge {
	return _newObservable(ObservableKindGauge, name, callback, opts)
}

// NewObservableUpDownCounter registers callback as a non-monotonic sum; see
// NewObservableCounter.
func NewObservableUpDownCounter(name string, callback ObservableCallback, opts ...Option) ObservableUpDownCounter {
	return _newObservable(ObservableKindUpDownCounter, name, callback, opts)
}

type _observableRegistration struct {
	once       sync.Once
	unregister func()
}

func (r *_observableRegistration) Unregister() { r.once.Do(r.unregister) }

func _newObservable(kind ObservableKind, name string, callback ObservableCallback, opts []Option) *_observableRegistration {
	if backend, ok := _activeBackend().(ObservableBackend); ok {
		if unregister, ok := backend.NewObservable(kind, name, _applyOptions(opts).snapshot(), _gatedCallback(name, callback)); ok {
			return &_observableRegistration{unregister: unregister}
		}
	}
	return &_observableRegistration{unregister: func() {}}
}

// _gatedCallback applies the collection-time metrics gates to callback,
// recovers a panic, and warns once per instrument when one happens.
func _gatedCallback(name string, callback ObservableCallback) ObservableCallback {
	var warned atomic.Bool
	return func(ctx context.Context) (observations []Observation) {
		if callback == nil || !MetricsEnabled() || !ShouldAllow(signalMetrics, "") {
			return nil
		}
		defer func() {
			if r := recover(); r != nil {
				observations = nil
				if logger := Logger(); logger != nil && warned.CompareAndSwap(false, true) {
					logger.Warn("metrics.observable_callback_panicked",
						slog.String("instrument", name), slog.String("panic", fmt.Sprint(r)))
				}
			}
		}()
		observations = callback(ctx)
		for range observations {
			_incMetricsRecorded()
		}
		return observations
	}
}
