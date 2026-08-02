// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

// What the facade reports before SetupTelemetry has run, and how the
// provider-immutability error answers errors.As.
//
// Split out of runtime_facade_contract_test.go to keep that file inside the
// 500-line ceiling scripts/check_max_loc.py enforces.

import (
	"context"
	"errors"
	"testing"
)

// Before SetupTelemetry the flush entry points short-circuit and drain nothing,
// so a provider a host put on the OTel globals is visible in Providers but
// untouched. Reporting it Flushed tells a caller its records are out while they
// sit in the host's batch processor — the aggregate nil means "nothing ran",
// not "the drain succeeded".
func TestFlush_ReportsNotOwnedBeforeSetup(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	_installPerSignalBackend(t,
		map[string]error{SignalLogs: nil, SignalTraces: nil, SignalMetrics: nil},
		SignalStatus{Logs: true, Traces: true, Metrics: true},
	)

	// Deliberately no Start(): the host's provider is installed, ours is not.
	rt := NewTelemetryRuntime(context.Background())

	result, err := rt.Flush(context.Background())
	if err != nil {
		t.Fatalf("flush: %v", err)
	}
	for name, sig := range map[string]SignalFlushResult{
		"logs":    result.Logs,
		"traces":  result.Traces,
		"metrics": result.Metrics,
	} {
		if !sig.NotOwned {
			t.Fatalf("expected %s NotOwned before setup, got %+v", name, sig)
		}
		if sig.Flushed {
			t.Fatalf("%s drained nothing and must not report Flushed: %+v", name, sig)
		}
	}
}

// The pre-setup path must not swallow NotInstalled: a signal with no provider
// at all is still NotInstalled, not NotOwned.
func TestFlush_NotInstalledStillWinsBeforeSetup(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	_installPerSignalBackend(t,
		map[string]error{SignalLogs: nil},
		SignalStatus{Logs: true},
	)

	rt := NewTelemetryRuntime(context.Background())

	result, _ := rt.Flush(context.Background())
	if !result.Logs.NotOwned {
		t.Fatalf("expected logs NotOwned before setup, got %+v", result.Logs)
	}
	for name, sig := range map[string]SignalFlushResult{"traces": result.Traces, "metrics": result.Metrics} {
		if !sig.NotInstalled || sig.NotOwned {
			t.Fatalf("expected %s NotInstalled only, got %+v", name, sig)
		}
	}
}

// ProviderImmutableError.As answers only for the two error types it wraps.
// Returning true for anything else would make errors.As populate a target of
// an unrelated type with this error's fields.
func TestProviderImmutableError_AsRejectsAnUnrelatedTarget(t *testing.T) {
	err := NewProviderImmutableError("providers are installed")

	var schemaErr *EventSchemaError
	if err.As(&schemaErr) {
		t.Fatal("As must not claim an unrelated error type")
	}
	if schemaErr != nil {
		t.Fatalf("a rejected target must be left alone, got %+v", schemaErr)
	}

	// The two it does answer for still match.
	var cfgErr *ConfigurationError
	if !errors.As(error(err), &cfgErr) {
		t.Fatal("expected ConfigurationError to match")
	}
	var telErr *TelemetryError
	if !errors.As(error(err), &telErr) {
		t.Fatal("expected TelemetryError to match")
	}
}

// Before SetupTelemetry there is no live config to compare against, so no field
// can be provider-changing yet. The call still fails — nothing is set up — but
// it must fail for that reason and not be turned away as an attempt to change
// an installed provider, which would send a caller off to restart a process
// that had never started.
func TestUpdateConfig_DoesNotBlameProviderFieldsBeforeSetup(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	rt := NewTelemetryRuntime(context.Background())
	cfg := DefaultTelemetryConfig()
	cfg.ServiceName = "renamed-before-setup"

	_, err := rt.UpdateConfig(context.Background(), cfg)
	if err == nil {
		t.Fatal("expected UpdateConfig to fail before setup")
	}
	var immutable *ProviderImmutableError
	if errors.As(err, &immutable) {
		t.Fatalf("provider-immutability must not be the complaint before setup: %v", err)
	}
}
