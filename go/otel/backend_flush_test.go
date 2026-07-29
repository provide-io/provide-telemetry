// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"testing"

	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
)

// ForceFlush must drain every installed provider and leave all three installed
// — the drain half of Shutdown, which nils them out.
func TestBackendForceFlush_DrainsAndLeavesProvidersInstalled(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	tp, _ := newInMemoryTP()
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(sdkmetric.NewManualReader()))
	lp := sdklog.NewLoggerProvider()

	_otelTracerProvider = tp
	_otelMeterProvider = mp
	_otelLoggerProvider = lp

	backend := &_backend{}
	if err := backend.ForceFlush(context.Background()); err != nil {
		t.Fatalf("ForceFlush returned %v, want nil", err)
	}

	if _otelTracerProvider == nil || _otelMeterProvider == nil || _otelLoggerProvider == nil {
		t.Fatal("ForceFlush tore providers down; they must stay installed")
	}
	// Repeatable, because nothing was torn down.
	if err := backend.ForceFlush(context.Background()); err != nil {
		t.Fatalf("second ForceFlush returned %v, want nil", err)
	}
}

func TestBackendForceFlush_IsANoopWithNoProviders(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	_otelTracerProvider = nil
	_otelMeterProvider = nil
	_otelLoggerProvider = nil

	if err := (&_backend{}).ForceFlush(context.Background()); err != nil {
		t.Fatalf("ForceFlush with no providers returned %v, want nil", err)
	}
}
