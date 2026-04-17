// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"sync"
	"testing"

	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
)

func TestGetRuntimeStatus_NoRaceWithProviderMutation(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	tp, _ := newInMemoryTP()
	mp := sdkmetric.NewMeterProvider()
	lp := sdklog.NewLoggerProvider()

	var wg sync.WaitGroup
	wg.Add(2)

	go func() {
		defer wg.Done()
		for i := 0; i < 200; i++ {
			_setupMu.Lock()
			_setupDone = true
			_runtimeCfg = DefaultTelemetryConfig()
			_otelTracerProvider = tp
			_otelMeterProvider = mp
			_otelLoggerProvider = lp
			_setupMu.Unlock()

			_setupMu.Lock()
			_setupDone = false
			_runtimeCfg = nil
			_otelTracerProvider = nil
			_otelMeterProvider = nil
			_otelLoggerProvider = nil
			_setupMu.Unlock()
		}
	}()

	go func() {
		defer wg.Done()
		for i := 0; i < 200; i++ {
			_ = GetRuntimeStatus()
		}
	}()

	wg.Wait()
}
