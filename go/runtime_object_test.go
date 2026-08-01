// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"errors"
	"testing"
)

type _testRuntimeFlushableBackend struct {
	_fakeBackend
	forceErr error
}

func (b *_testRuntimeFlushableBackend) ForceFlush(context.Context) error {
	return b.forceErr
}

func TestTelemetryRuntime_NewTelemetryRuntime(t *testing.T) {
	rt := NewTelemetryRuntime(context.Background())
	if rt == nil {
		t.Fatal("expected runtime instance")
	}
	if rt.state != RuntimeStateReady {
		t.Fatalf("expected new runtime state=%q, got=%q", RuntimeStateReady, rt.state)
	}
	if rt.providerMode != ProviderModeOwned {
		t.Fatalf("expected provider mode=%q, got=%q", ProviderModeOwned, rt.providerMode)
	}
}

func TestTelemetryRuntime_StartAndRuntimeMethods(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	cfg := DefaultTelemetryConfig()
	cfg.ServiceName = "go-runtime-object"
	rt := NewTelemetryRuntime(context.Background())

	started, err := rt.Start(context.Background(), WithConfig(cfg))
	if err != nil {
		t.Fatalf("start failed: %v", err)
	}
	if started == nil {
		t.Fatal("start returned nil config")
	}
	if started.ServiceName != cfg.ServiceName {
		t.Fatalf("expected started service name %q, got %q", cfg.ServiceName, started.ServiceName)
	}

	logger := rt.GetLogger(context.Background(), "runtime.object")
	if logger == nil {
		t.Fatal("GetLogger returned nil")
	}

	tracer := rt.GetTracer(context.Background(), "runtime.object")
	if tracer == nil {
		t.Fatal("GetTracer returned nil")
	}

	meter := rt.GetMeter("runtime.object")
	_ = meter

	seen := rt.GetRuntimeConfig()
	if seen == nil {
		t.Fatal("GetRuntimeConfig returned nil after start")
	}
	if seen.ServiceName != cfg.ServiceName {
		t.Fatalf("expected get-config service name %q, got %q", cfg.ServiceName, seen.ServiceName)
	}
	status := rt.GetRuntimeStatus()
	if !status.SetupDone {
		t.Fatal("expected runtime status setup_done=true after start")
	}
	// Local-only status can vary based on active backends, but setup must be complete.
	if status.Signals.Traces == false {
		t.Fatal("expected tracing signal status to remain discoverable from runtime status")
	}

	// No backend is registered in this test, so no signal has a provider to
	// drain: every signal must report NotInstalled rather than a bare Flushed.
	flushResult, flushErr := rt.Flush(context.Background())
	if flushErr != nil {
		t.Fatalf("flush returned unexpected error: %v", flushErr)
	}
	for name, sig := range map[string]SignalFlushResult{
		"logs": flushResult.Logs, "traces": flushResult.Traces, "metrics": flushResult.Metrics,
	} {
		if !sig.NotInstalled {
			t.Fatalf("expected %s not_installed=true with no provider installed, got %+v", name, sig)
		}
		if sig.Flushed || sig.Failed {
			t.Fatalf("expected %s flushed=false failed=false with no provider, got %+v", name, sig)
		}
	}
}

func TestTelemetryRuntime_FlushReportsInstalledSignals(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	backend := &_testRuntimeFlushableBackend{}
	backend.providers = SignalStatus{Logs: true, Traces: true, Metrics: true}
	previous, replaced := RegisterBackend("runtime-flush-ok", backend)
	t.Cleanup(func() {
		if replaced {
			RegisterBackend("runtime-flush-ok", previous)
		} else {
			UnregisterBackend("runtime-flush-ok")
		}
	})

	rt := NewTelemetryRuntime(context.Background())
	if _, err := rt.Start(context.Background(), WithConfig(DefaultTelemetryConfig())); err != nil {
		t.Fatalf("start failed: %v", err)
	}
	result, err := rt.Flush(context.Background())
	if err != nil {
		t.Fatalf("flush returned unexpected error: %v", err)
	}
	if !result.Logs.Flushed || !result.Traces.Flushed || !result.Metrics.Flushed {
		t.Fatalf("expected all signals flushed=true, got %+v", result)
	}
	if result.Logs.NotInstalled || result.Traces.NotInstalled || result.Metrics.NotInstalled {
		t.Fatalf("expected no signal not_installed with providers live, got %+v", result)
	}
}

func TestTelemetryRuntime_FlushErrorPath(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	errorBackend := &_testRuntimeFlushableBackend{
		forceErr: errors.New("flush backend failure"),
	}
	errorBackend.providers = SignalStatus{Logs: true, Traces: true, Metrics: true}
	expectedErr := errorBackend.forceErr
	previous, replaced := RegisterBackend("runtime-flush-fail", errorBackend)
	t.Cleanup(func() {
		if replaced {
			RegisterBackend("runtime-flush-fail", previous)
		} else {
			UnregisterBackend("runtime-flush-fail")
		}
	})

	rt := NewTelemetryRuntime(context.Background())
	if _, err := rt.Start(context.Background(), WithConfig(DefaultTelemetryConfig())); err != nil {
		t.Fatalf("start failed: %v", err)
	}
	result, err := rt.Flush(context.Background())
	if err == nil {
		t.Fatal("expected flush to return error")
	}
	if !errors.Is(err, expectedErr) {
		t.Fatalf("unexpected flush error: %v", err)
	}
	if !result.Logs.Failed || !result.Traces.Failed || !result.Metrics.Failed {
		t.Fatal("expected failed=true for all flush results on error")
	}
}

func TestTelemetryRuntime_UpdateConfigAndReconfigure(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	rt := NewTelemetryRuntime(context.Background())
	if _, err := rt.Start(context.Background(), WithConfig(DefaultTelemetryConfig())); err != nil {
		t.Fatalf("start failed: %v", err)
	}

	if _, err := rt.UpdateConfig(context.Background(), DefaultTelemetryConfig()); err != nil {
		t.Fatalf("update config failed: %v", err)
	}
	if _, err := rt.Reconfigure(context.Background(), DefaultTelemetryConfig()); err != nil {
		t.Fatalf("reconfigure failed: %v", err)
	}

	t.Setenv("PROVIDE_TELEMETRY_SERVICE_NAME", "updated")
	if _, err := rt.Reconfigure(context.Background(), nil); err != nil {
		t.Fatalf("reconfigure without config should read env and succeed: %v", err)
	}
}

func TestTelemetryRuntime_ShutdownSetsStoppingState(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	rt := NewTelemetryRuntime(context.Background())
	if _, err := rt.Start(context.Background(), WithConfig(DefaultTelemetryConfig())); err != nil {
		t.Fatalf("start failed: %v", err)
	}

	if rt.state != RuntimeStateReady {
		t.Fatalf("expected state=%q before shutdown, got=%q", RuntimeStateReady, rt.state)
	}

	if err := rt.Shutdown(context.Background()); err != nil {
		t.Fatalf("shutdown failed: %v", err)
	}
	if rt.state != RuntimeStateStopped {
		t.Fatalf("expected state=%q after shutdown, got=%q", RuntimeStateStopped, rt.state)
	}
}

func TestProviderImmutableErrorIsDistinctFromConfigurationError(t *testing.T) {
	// The restart-on-immutable-provider contract is only actionable if a plain
	// configuration error does not also satisfy it.
	pie := error(NewProviderImmutableError("providers already installed"))
	cfgErr := error(NewConfigurationError("sample_rate must be in [0.0, 1.0]"))

	var asImmutable *ProviderImmutableError
	if !errors.As(pie, &asImmutable) {
		t.Fatal("expected ProviderImmutableError to match errors.As for its own type")
	}
	asImmutable = nil
	if errors.As(cfgErr, &asImmutable) {
		t.Fatal("a plain ConfigurationError must NOT match *ProviderImmutableError")
	}

	// Legacy callers matching the broader type must keep working.
	var asConfig *ConfigurationError
	if !errors.As(pie, &asConfig) {
		t.Fatal("expected ProviderImmutableError to still match *ConfigurationError")
	}
	var asBase *TelemetryError
	if !errors.As(pie, &asBase) {
		t.Fatal("expected ProviderImmutableError to still match *TelemetryError")
	}
	if asImmutable != nil {
		t.Fatal("errors.As must leave the target nil when it does not match")
	}
}

func TestTelemetryRuntime_UpdateConfigAppliesCallerConfig(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	rt := NewTelemetryRuntime(context.Background())
	if _, err := rt.Start(context.Background(), WithConfig(DefaultTelemetryConfig())); err != nil {
		t.Fatalf("start failed: %v", err)
	}

	next := DefaultTelemetryConfig()
	next.Sampling.LogsRate = 0.25
	updated, err := rt.UpdateConfig(context.Background(), next)
	if err != nil {
		t.Fatalf("update config failed: %v", err)
	}
	if updated == nil {
		t.Fatal("UpdateConfig must return the resulting config, not nil")
	}
	if updated.Sampling.LogsRate != 0.25 {
		t.Fatalf("expected caller's logs rate 0.25 to be applied, got %v", updated.Sampling.LogsRate)
	}
	if live := GetRuntimeConfig(); live.Sampling.LogsRate != 0.25 {
		t.Fatalf("expected live config to carry the update, got %v", live.Sampling.LogsRate)
	}
}

func TestTelemetryRuntime_UpdateConfigRejectsNil(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	rt := NewTelemetryRuntime(context.Background())
	if _, err := rt.Start(context.Background(), WithConfig(DefaultTelemetryConfig())); err != nil {
		t.Fatalf("start failed: %v", err)
	}
	cfg, err := rt.UpdateConfig(context.Background(), nil)
	if err == nil {
		t.Fatal("expected an error for a nil config")
	}
	if cfg != nil {
		t.Fatal("expected a nil config alongside the error")
	}
}

func TestTelemetryRuntime_ReconfigureAppliesCallerConfig(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	rt := NewTelemetryRuntime(context.Background())
	if _, err := rt.Start(context.Background(), WithConfig(DefaultTelemetryConfig())); err != nil {
		t.Fatalf("start failed: %v", err)
	}

	// The environment says one thing; the explicit config must win.
	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "0.9")
	next := DefaultTelemetryConfig()
	next.Sampling.LogsRate = 0.1
	got, err := rt.Reconfigure(context.Background(), next)
	if err != nil {
		t.Fatalf("reconfigure failed: %v", err)
	}
	if got.Sampling.LogsRate != 0.1 {
		t.Fatalf("expected the caller's config to win over the environment, got %v", got.Sampling.LogsRate)
	}
}

func TestNewTelemetryRuntimeRetainsConstructorOptions(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	cfg := DefaultTelemetryConfig()
	cfg.ServiceName = "from-constructor"
	rt := NewTelemetryRuntime(context.Background(), WithConfig(cfg))

	started, err := rt.Start(context.Background())
	if err != nil {
		t.Fatalf("start failed: %v", err)
	}
	if started.ServiceName != "from-constructor" {
		t.Fatalf("constructor options must reach Start, got service name %q", started.ServiceName)
	}
}

func TestTelemetryRuntimeStartOptionOverridesConstructorOption(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	ctorCfg := DefaultTelemetryConfig()
	ctorCfg.ServiceName = "from-constructor"
	callCfg := DefaultTelemetryConfig()
	callCfg.ServiceName = "from-start"

	rt := NewTelemetryRuntime(context.Background(), WithConfig(ctorCfg))
	started, err := rt.Start(context.Background(), WithConfig(callCfg))
	if err != nil {
		t.Fatalf("start failed: %v", err)
	}
	if started.ServiceName != "from-start" {
		t.Fatalf("per-call option must win over the constructor's, got %q", started.ServiceName)
	}
}

func TestTelemetryRuntime_UpdateConfigSurfacesValidationErrors(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	rt := NewTelemetryRuntime(context.Background())
	if _, err := rt.Start(context.Background(), WithConfig(DefaultTelemetryConfig())); err != nil {
		t.Fatalf("start failed: %v", err)
	}

	// An out-of-range rate is rejected by UpdateRuntimeConfig; the facade must
	// propagate that error rather than reporting a successful update.
	bad := DefaultTelemetryConfig()
	bad.Sampling.LogsRate = 2.0
	cfg, err := rt.UpdateConfig(context.Background(), bad)
	if err == nil {
		t.Fatal("expected an error for an out-of-range sampling rate")
	}
	if cfg != nil {
		t.Fatal("expected a nil config alongside the error")
	}
	if live := GetRuntimeConfig(); live.Sampling.LogsRate == 2.0 {
		t.Fatal("a rejected update must not reach the live config")
	}
}
