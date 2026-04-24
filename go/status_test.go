// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"testing"
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

func TestGetRuntimeStatus_BeforeSetup_ConfigFromEnvErrorFallsBackToDefaults(t *testing.T) {
	ResetForTests()
	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "not-a-float")

	status := GetRuntimeStatus()

	if status.SetupDone {
		t.Fatal("setup_done should be false before setup")
	}
	if !status.Signals.Logs || !status.Signals.Traces || !status.Signals.Metrics {
		t.Fatalf("expected default-enabled signals after config parse failure, got %+v", status.Signals)
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
	backend := &_fakeBackend{
		providers: SignalStatus{
			Logs:    true,
			Traces:  false,
			Metrics: true,
		},
	}
	_registeredBackends["fake"] = backend
	_activeBackendName = "fake"
	_setupMu.Unlock()
	t.Cleanup(func() {
		_setupMu.Lock()
		_setupDone = false
		_runtimeCfg = nil
		delete(_registeredBackends, "fake")
		_activeBackendName = ""
		_setupMu.Unlock()
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
