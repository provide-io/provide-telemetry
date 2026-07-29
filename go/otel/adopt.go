// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"sync"

	telemetry "github.com/provide-io/provide-telemetry/go"
	"go.opentelemetry.io/otel"
	otelmetric "go.opentelemetry.io/otel/metric"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	oteltrace "go.opentelemetry.io/otel/trace"
)

// _providersMu guards the installed-provider globals and the ownership flags.
//
// Provider resolution happens per span now, so these are read from every traced
// call while Setup and Shutdown write them from another goroutine. The pre-diff
// code only read them during Setup, under the root package's _setupMu, and so
// needed no lock of its own.
var _providersMu sync.RWMutex //nolint:gochecknoglobals

// Signal enablement is deliberately NOT cached in this package. It lived as a
// pair of flags captured during Setup, which was wrong twice over:
// _setupBackendLocked skips Setup entirely when no provider options and no OTLP
// endpoint are configured (the pure-adoption path), leaving the flags stale;
// and Shutdown latched them off with no path back, so adoption died after one
// shutdown/setup cycle. The root package owns the runtime config, so the gate
// lives there — one source of truth, nothing to go stale.

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

// ── guarded reads of the installed providers ──────────────────────────

func _loadTracerProvider() *sdktrace.TracerProvider {
	_providersMu.RLock()
	defer _providersMu.RUnlock()
	return _otelTracerProvider
}

func _loadMeterProvider() *sdkmetric.MeterProvider {
	_providersMu.RLock()
	defer _providersMu.RUnlock()
	return _otelMeterProvider
}

func _loadLoggerProvider() *sdklog.LoggerProvider {
	_providersMu.RLock()
	defer _providersMu.RUnlock()
	return _otelLoggerProvider
}

// ── effective providers ───────────────────────────────────────────────

// _effectiveTracerProvider returns the provider facade spans go through: ours
// when we installed one, otherwise a host application's if one owns the global,
// otherwise nil.
//
// The global is probed on every call rather than snapshotted during Setup. An
// auto-instrumentation agent or vendor distro may register itself after our
// setup runs — a lazily-initialised SDK, a framework hook, an agent loaded on a
// later import — and a snapshot would miss it forever. This matches the
// TypeScript facade, which resolves the provider per call for the same reason.
//
// Gated on the signal being enabled, because that is what the emit paths check
// first: reporting or using a provider for a signal the caller switched off
// would claim an export path nothing is meant to reach.
func _effectiveTracerProvider() oteltrace.TracerProvider {
	if !telemetry.TracingEnabled() {
		return nil
	}
	if tp := _loadTracerProvider(); tp != nil {
		return tp
	}
	if tp := otel.GetTracerProvider(); _isLiveProvider(tp) {
		return tp
	}
	return nil
}

// _effectiveMeterProvider is the metrics counterpart of _effectiveTracerProvider.
func _effectiveMeterProvider() otelmetric.MeterProvider {
	if !telemetry.MetricsEnabled() {
		return nil
	}
	if mp := _loadMeterProvider(); mp != nil {
		return mp
	}
	if mp := otel.GetMeterProvider(); _isLiveProvider(mp) {
		return mp
	}
	return nil
}
