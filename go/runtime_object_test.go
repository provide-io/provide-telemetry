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

	flushResult, flushErr := rt.Flush(context.Background())
	if flushErr != nil {
		t.Fatalf("flush returned unexpected error: %v", flushErr)
	}
	if !flushResult.Logs.Flushed || !flushResult.Traces.Flushed || !flushResult.Metrics.Flushed {
		t.Fatal("expected all flush results flushed=true")
	}
}

func TestTelemetryRuntime_FlushErrorPath(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	errorBackend := &_testRuntimeFlushableBackend{
		forceErr: errors.New("flush backend failure"),
	}
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
