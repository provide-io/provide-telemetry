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

// Providers a host application installed on the OTel globals. We emit through
// them but never own them: Shutdown drops the reference without tearing them
// down, and ForceFlush leaves them alone — draining someone else's exporter is
// not ours to do.
var (
	_adoptedTracerProvider oteltrace.TracerProvider //nolint:gochecknoglobals
	_adoptedMeterProvider  otelmetric.MeterProvider //nolint:gochecknoglobals
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

// _adoptForeignProviders picks up a provider a host application installed on the
// OTel globals, for the signals where we installed none of our own.
//
// Without this the facade would emit no-op spans while the host's SDK sat right
// there on the global — the Python and TypeScript facades resolve their tracer
// off the global and have always honoured it. Called at the end of Setup, after
// our own providers (if any) are installed, so ours always win.
func _adoptForeignProviders(cfg *telemetry.TelemetryConfig) {
	if cfg.Tracing.Enabled && _otelTracerProvider == nil {
		if tp := otel.GetTracerProvider(); _isLiveProvider(tp) {
			_adoptedTracerProvider = tp
		}
	}
	if cfg.Metrics.Enabled && _otelMeterProvider == nil {
		if mp := otel.GetMeterProvider(); _isLiveProvider(mp) {
			_adoptedMeterProvider = mp
		}
	}
}

// _effectiveTracerProvider returns the provider facade spans go through: ours
// when we installed one, otherwise a host's that we adopted, otherwise nil.
func _effectiveTracerProvider() oteltrace.TracerProvider {
	if _otelTracerProvider != nil {
		return _otelTracerProvider
	}
	if _adoptedTracerProvider != nil {
		return _adoptedTracerProvider
	}
	return nil
}

// _effectiveMeterProvider is the metrics counterpart of _effectiveTracerProvider.
func _effectiveMeterProvider() otelmetric.MeterProvider {
	if _otelMeterProvider != nil {
		return _otelMeterProvider
	}
	if _adoptedMeterProvider != nil {
		return _adoptedMeterProvider
	}
	return nil
}

// _releaseAdoptedProviders drops adopted references without shutting anything
// down — the host owns their lifecycle.
func _releaseAdoptedProviders() {
	_adoptedTracerProvider = nil
	_adoptedMeterProvider = nil
}
