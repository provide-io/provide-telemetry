// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"testing"

	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
)

func TestGetRuntimeStatus_BeforeSetup_UsesFallback(t *testing.T) {
	ResetForTests()

	status := GetRuntimeStatus()

	if status.SetupDone {
		t.Fatal("setup_done should be false before setup")
	}
	if status.Providers.Logs || status.Providers.Traces || status.Providers.Metrics {
		t.Fatalf("expected no providers before setup, got %+v", status.Providers)
	}
	if !status.Fallback.Logs || !status.Fallback.Traces || !status.Fallback.Metrics {
		t.Fatalf("expected fallback mode before setup, got %+v", status.Fallback)
	}
}

func TestGetRuntimeStatus_ReportsProviderState(t *testing.T) {
	ResetForTests()
	_setupMu.Lock()
	_setupDone = true
	_runtimeCfg = DefaultTelemetryConfig()
	_setupMu.Unlock()
	_otelLoggerProvider = &noopLoggerProvider
	_otelMeterProvider = &noopMeterProvider
	t.Cleanup(func() {
		_setupMu.Lock()
		_setupDone = false
		_runtimeCfg = nil
		_setupMu.Unlock()
		_otelLoggerProvider = nil
		_otelMeterProvider = nil
	})

	status := GetRuntimeStatus()

	if !status.SetupDone {
		t.Fatal("setup_done should be true after setup")
	}
	if !status.Signals.Logs || !status.Signals.Traces || !status.Signals.Metrics {
		t.Fatalf("expected signals enabled from default config, got %+v", status.Signals)
	}
	if !status.Providers.Logs || status.Providers.Traces || !status.Providers.Metrics {
		t.Fatalf("unexpected providers %+v", status.Providers)
	}
	if status.Fallback.Logs || !status.Fallback.Traces || status.Fallback.Metrics {
		t.Fatalf("unexpected fallback %+v", status.Fallback)
	}
}

var noopLoggerProvider = sdklog.LoggerProvider{}
var noopMeterProvider = sdkmetric.MeterProvider{}
