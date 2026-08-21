// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"testing"

	"go.opentelemetry.io/otel"
	otellog "go.opentelemetry.io/otel/log"
	logglobal "go.opentelemetry.io/otel/log/global"
	otelmetric "go.opentelemetry.io/otel/metric"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	oteltrace "go.opentelemetry.io/otel/trace"
)

// A host that installs its own provider AFTER our Setup owns the global from
// that moment on. Our Shutdown must not overwrite it: the ownership flag says
// "we registered one once", but the global no longer holds the provider we
// registered, so there is nothing of ours left to undo.

func TestShutdown_LeavesALateHostTracerProviderInstalled(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetOTelGlobal(t); resetSetupState(t) })

	ours := sdktrace.NewTracerProvider()
	_providersMu.Lock()
	_otelTracerProvider = ours
	otel.SetTracerProvider(ours)
	_weSetTracerGlobal = true
	_providersMu.Unlock()

	// The host replaces the global afterwards — an auto-instrumentation agent,
	// a vendor distro, a lazily-initialised SDK.
	hostTP := sdktrace.NewTracerProvider()
	t.Cleanup(func() { _ = hostTP.Shutdown(context.Background()) })
	otel.SetTracerProvider(hostTP)

	if err := (&_backend{}).Shutdown(context.Background()); err != nil {
		t.Fatalf("Shutdown failed: %v", err)
	}

	if got := otel.GetTracerProvider(); got != oteltrace.TracerProvider(hostTP) {
		t.Fatalf("shutdown replaced the host's tracer provider: got %T", got)
	}
}

func TestShutdown_LeavesALateHostMeterProviderInstalled(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetOTelGlobal(t); resetSetupState(t) })

	ours := sdkmetric.NewMeterProvider()
	_providersMu.Lock()
	_otelMeterProvider = ours
	otel.SetMeterProvider(ours)
	_weSetMeterGlobal = true
	_providersMu.Unlock()

	hostMP := sdkmetric.NewMeterProvider()
	t.Cleanup(func() { _ = hostMP.Shutdown(context.Background()) })
	otel.SetMeterProvider(hostMP)

	if err := (&_backend{}).Shutdown(context.Background()); err != nil {
		t.Fatalf("Shutdown failed: %v", err)
	}

	if got := otel.GetMeterProvider(); got != otelmetric.MeterProvider(hostMP) {
		t.Fatalf("shutdown replaced the host's meter provider: got %T", got)
	}
}

func TestShutdown_LeavesALateHostLoggerProviderInstalled(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetOTelGlobal(t); resetSetupState(t) })

	ours := sdklog.NewLoggerProvider()
	_providersMu.Lock()
	_otelLoggerProvider = ours
	logglobal.SetLoggerProvider(ours)
	_weSetLoggerGlobal = true
	_providersMu.Unlock()

	hostLP := sdklog.NewLoggerProvider()
	t.Cleanup(func() { _ = hostLP.Shutdown(context.Background()) })
	logglobal.SetLoggerProvider(hostLP)

	if err := (&_backend{}).Shutdown(context.Background()); err != nil {
		t.Fatalf("Shutdown failed: %v", err)
	}

	if got := logglobal.GetLoggerProvider(); got != otellog.LoggerProvider(hostLP) {
		t.Fatalf("shutdown replaced the host's logger provider: got %T", got)
	}
}

// The other half of the contract. Without these, the identity check could be
// mutated to a constant false and every test above would still pass.

func TestShutdown_StillResetsOurOwnTracerGlobal(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetOTelGlobal(t); resetSetupState(t) })

	ours := sdktrace.NewTracerProvider()
	_providersMu.Lock()
	_otelTracerProvider = ours
	otel.SetTracerProvider(ours)
	_weSetTracerGlobal = true
	_providersMu.Unlock()

	if err := (&_backend{}).Shutdown(context.Background()); err != nil {
		t.Fatalf("Shutdown failed: %v", err)
	}

	if got := otel.GetTracerProvider(); got == oteltrace.TracerProvider(ours) {
		t.Fatal("shutdown left our own tracer provider registered globally")
	}
}

func TestShutdown_StillResetsOurOwnMeterGlobal(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetOTelGlobal(t); resetSetupState(t) })

	ours := sdkmetric.NewMeterProvider()
	_providersMu.Lock()
	_otelMeterProvider = ours
	otel.SetMeterProvider(ours)
	_weSetMeterGlobal = true
	_providersMu.Unlock()

	if err := (&_backend{}).Shutdown(context.Background()); err != nil {
		t.Fatalf("Shutdown failed: %v", err)
	}

	if got := otel.GetMeterProvider(); got == otelmetric.MeterProvider(ours) {
		t.Fatal("shutdown left our own meter provider registered globally")
	}
}

func TestShutdown_StillResetsOurOwnLoggerGlobal(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetOTelGlobal(t); resetSetupState(t) })

	ours := sdklog.NewLoggerProvider()
	_providersMu.Lock()
	_otelLoggerProvider = ours
	logglobal.SetLoggerProvider(ours)
	_weSetLoggerGlobal = true
	_providersMu.Unlock()

	if err := (&_backend{}).Shutdown(context.Background()); err != nil {
		t.Fatalf("Shutdown failed: %v", err)
	}

	if got := logglobal.GetLoggerProvider(); got == otellog.LoggerProvider(ours) {
		t.Fatal("shutdown left our own logger provider registered globally")
	}
}
