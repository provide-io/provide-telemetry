// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"

	telemetry "github.com/provide-io/provide-telemetry/go"
	"go.opentelemetry.io/otel/attribute"
	otelmetric "go.opentelemetry.io/otel/metric"
)

// NewObservable implements telemetry.ObservableBackend.
func (b *_backend) NewObservable(
	kind telemetry.ObservableKind, name string, opts telemetry.InstrumentOptions, callback telemetry.ObservableCallback,
) (func(), bool) {
	provider := _effectiveMeterProvider()
	if provider == nil {
		return nil, false
	}
	return _registerObservable(provider.Meter("provide.telemetry"), kind, name, opts, callback)
}

// _registerObservable creates the instrument and registers callback on it.
// RegisterCallback rather than an instrument callback option, because only a
// registration can be unregistered.
func _registerObservable(
	meter otelmetric.Meter, kind telemetry.ObservableKind, name string, opts telemetry.InstrumentOptions,
	callback telemetry.ObservableCallback,
) (func(), bool) {
	instrument, err := _observableInstrument(meter, kind, name, opts)
	if err != nil {
		return nil, false
	}
	registration, err := meter.RegisterCallback(func(ctx context.Context, o otelmetric.Observer) error {
		for _, observation := range callback(ctx) {
			attrs := make([]attribute.KeyValue, 0, len(observation.Attrs))
			for _, a := range observation.Attrs {
				attrs = append(attrs, _attributeFromSlogAttr(a))
			}
			o.ObserveFloat64(instrument, observation.Value, otelmetric.WithAttributes(attrs...))
		}
		return nil
	}, instrument)
	if err != nil {
		return nil, false
	}
	return func() { _ = registration.Unregister() }, true
}

func _observableInstrument(
	meter otelmetric.Meter, kind telemetry.ObservableKind, name string, opts telemetry.InstrumentOptions,
) (otelmetric.Float64Observable, error) {
	options := []otelmetric.InstrumentOption{otelmetric.WithDescription(opts.Description), otelmetric.WithUnit(opts.Unit)}
	switch kind {
	case telemetry.ObservableKindCounter:
		return meter.Float64ObservableCounter(name, _asOptions[otelmetric.Float64ObservableCounterOption](options)...)
	case telemetry.ObservableKindGauge:
		return meter.Float64ObservableGauge(name, _asOptions[otelmetric.Float64ObservableGaugeOption](options)...)
	default:
		return meter.Float64ObservableUpDownCounter(name, _asOptions[otelmetric.Float64ObservableUpDownCounterOption](options)...)
	}
}

// _asOptions narrows the shared description/unit options to one instrument's option type.
func _asOptions[T any](options []otelmetric.InstrumentOption) []T {
	out := make([]T, 0, len(options))
	for _, o := range options {
		out = append(out, any(o).(T))
	}
	return out
}
