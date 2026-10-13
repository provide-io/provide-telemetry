// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"

	telemetry "github.com/provide-io/provide-telemetry/go"
	"go.opentelemetry.io/otel/attribute"
	otelmetric "go.opentelemetry.io/otel/metric"
)

// _healthInstrument is one health family exported as an observable instrument
// when PROVIDE_METRICS_HEALTH_OTLP is set (spec prometheus_metrics.health_metrics).
// A per-signal family reads perSignal; a global one reads global.
type _healthInstrument struct {
	name      string
	gauge     bool
	perSignal func(_signalHealth) float64
	global    func(telemetry.HealthSnapshot) float64
}

var _healthInstruments = []_healthInstrument{ //nolint:gochecknoglobals
	{name: _healthEmitted, perSignal: func(s _signalHealth) float64 { return float64(s.emitted) }},
	{name: _healthDropped, perSignal: func(s _signalHealth) float64 { return float64(s.dropped) }},
	{name: _healthFailures, perSignal: func(s _signalHealth) float64 { return float64(s.failures) }},
	{name: _healthRetries, perSignal: func(s _signalHealth) float64 { return float64(s.retries) }},
	{name: _healthLatency, gauge: true, perSignal: func(s _signalHealth) float64 { return s.latencyMs }},
	{name: _healthBlockingRisk, perSignal: func(s _signalHealth) float64 { return float64(s.blockingRisk) }},
	{name: _healthCircuit, gauge: true, perSignal: func(s _signalHealth) float64 { return _circuitStateValue(s.circuitState) }},
	{name: _healthCircuitOpens, perSignal: func(s _signalHealth) float64 { return float64(s.circuitOpens) }},
	{name: _healthSetupError, gauge: true, global: _setupErrorValue},
	{name: _healthReceipts, global: func(s telemetry.HealthSnapshot) float64 { return float64(s.ReceiptFailures) }},
	{name: _healthReplacements, global: func(s telemetry.HealthSnapshot) float64 { return float64(s.ReservedFieldReplacements) }},
}

// _registerHealth is a seam so tests can make registration fail.
var _registerHealth = _registerHealthInstruments //nolint:gochecknoglobals

func _setupErrorValue(s telemetry.HealthSnapshot) float64 {
	if s.SetupError != "" {
		return 1
	}
	return 0
}

// _registerHealthInstruments creates the health families on meter as
// observables named verbatim. They describe the SDK rather than user data, so,
// unlike NewObservable*, they skip the consent gate and the emitted count.
func _registerHealthInstruments(meter otelmetric.Meter, snapshot func() telemetry.HealthSnapshot) error {
	instruments := make([]otelmetric.Float64Observable, len(_healthInstruments))
	observables := make([]otelmetric.Observable, len(_healthInstruments))
	for i, h := range _healthInstruments {
		instrument, err := _healthObservable(meter, h)
		if err != nil {
			return err
		}
		instruments[i], observables[i] = instrument, instrument
	}
	_, err := meter.RegisterCallback(func(_ context.Context, o otelmetric.Observer) error {
		s := snapshot()
		for i, h := range _healthInstruments {
			if h.global != nil {
				o.ObserveFloat64(instruments[i], h.global(s))
				continue
			}
			for _, sig := range _signalsOf(s) {
				o.ObserveFloat64(instruments[i], h.perSignal(sig), otelmetric.WithAttributes(attribute.String("signal", sig.name)))
			}
		}
		return nil
	}, observables...)
	return err
}

func _healthObservable(meter otelmetric.Meter, h _healthInstrument) (otelmetric.Float64Observable, error) {
	if h.gauge {
		return meter.Float64ObservableGauge(h.name)
	}
	return meter.Float64ObservableCounter(h.name)
}
