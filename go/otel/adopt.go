// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"

	telemetry "github.com/provide-io/provide-telemetry/go"
	"go.opentelemetry.io/otel"
	otelmetric "go.opentelemetry.io/otel/metric"
	oteltrace "go.opentelemetry.io/otel/trace"
)

// _isLiveProvider reports whether p is a real SDK provider rather than the API's
// delegating placeholder.
//
// Duck-typed on the ForceFlush/Shutdown lifecycle pair that every SDK provider
// implements and that the delegating global (`*internal/global.tracerProvider`,
// whose method set is just Tracer) does not. Deliberately not a type assertion
// to *sdktrace.TracerProvider: a host may run any implementation, and after
// otel.SetTracerProvider the global holds that provider itself rather than a
// wrapper, so the duck-type sees it directly.
func _isLiveProvider(p any) bool {
	if _, ok := p.(interface {
		ForceFlush(context.Context) error
	}); !ok {
		return false
	}
	_, ok := p.(interface {
		Shutdown(context.Context) error
	})
	return ok
}

// Signal enablement captured at Setup. A disabled signal never reports or uses
// a provider, however live the global is — Trace()/metrics gate on the same
// config upstream, and status must not claim a signal the caller switched off.
// Default to on so a direct provider install (tests, embedders wiring the
// backend by hand) works without a Setup call; Setup narrows them to the
// caller's config and Shutdown clears them.
var (
	_tracingEnabled = true //nolint:gochecknoglobals
	_metricsEnabled = true //nolint:gochecknoglobals
)

// _captureSignalEnablement records which signals this config leaves on.
func _captureSignalEnablement(cfg *telemetry.TelemetryConfig) {
	_tracingEnabled = cfg.Tracing.Enabled
	_metricsEnabled = cfg.Metrics.Enabled
}

// _effectiveTracerProvider returns the provider facade spans go through: ours
// when we installed one, otherwise a host application's if one owns the global,
// otherwise nil.
//
// The global is probed on every call rather than snapshotted during Setup. An
// auto-instrumentation agent or vendor distro may register itself after our
// setup runs — a lazily-initialised SDK, a framework hook, an agent loaded on a
// later import — and a snapshot would miss it forever. This matches the
// TypeScript facade, which resolves the provider per call for the same reason.
func _effectiveTracerProvider() oteltrace.TracerProvider {
	if !_tracingEnabled {
		return nil
	}
	if _otelTracerProvider != nil {
		return _otelTracerProvider
	}
	if tp := otel.GetTracerProvider(); _isLiveProvider(tp) {
		return tp
	}
	return nil
}

// _effectiveMeterProvider is the metrics counterpart of _effectiveTracerProvider.
func _effectiveMeterProvider() otelmetric.MeterProvider {
	if !_metricsEnabled {
		return nil
	}
	if _otelMeterProvider != nil {
		return _otelMeterProvider
	}
	if mp := otel.GetMeterProvider(); _isLiveProvider(mp) {
		return mp
	}
	return nil
}
