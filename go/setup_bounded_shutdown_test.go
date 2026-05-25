// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"errors"
	"testing"
	"time"
)

func TestShutdownTelemetry_AppliesBoundedDeadlineWhenCtxHasNone(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS", "0.05")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	// Background context has no deadline; ShutdownTelemetry must add one
	// derived from PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS so a
	// slow OTLP backend cannot block shutdown indefinitely.
	start := time.Now()
	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("shutdown failed: %v", err)
	}
	elapsed := time.Since(start)
	if elapsed > 500*time.Millisecond {
		t.Errorf("shutdown took %v, expected fast return under bounded deadline", elapsed)
	}
}

func TestShutdownTelemetry_HonoursCallerDeadline(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	// Caller supplies a context with a deadline — the library MUST NOT
	// overwrite it with its own. Tested via the internal helper to keep
	// the assertion deterministic (no real OTel I/O).
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	_setupMu.Lock()
	d := _shutdownDeadlineForLocked(ctx)
	_setupMu.Unlock()
	if d != 0 {
		t.Errorf("expected _shutdownDeadlineForLocked=0 when caller has deadline, got %v", d)
	}
}

func TestShutdownTelemetry_DisableBoundingWithZeroTimeout(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	// LogsShutdownTimeoutSeconds=0 means "no bound from the library" —
	// callers can opt out and rely on the OTel SDK / their own ctx.
	t.Setenv("PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS", "0")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	_setupMu.Lock()
	d := _shutdownDeadlineForLocked(context.Background())
	_setupMu.Unlock()
	if d != 0 {
		t.Errorf("expected no bounding when LogsShutdownTimeoutSeconds=0, got %v", d)
	}
}

func TestShutdownTelemetry_DeadlineHelperReturnsZeroWhenNoRuntimeConfig(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	// After resetSetupState _runtimeCfg is nil — the helper must return 0
	// rather than crashing on a nil dereference.
	_setupMu.Lock()
	d := _shutdownDeadlineForLocked(context.Background())
	_setupMu.Unlock()
	if d != 0 {
		t.Errorf("expected 0 when _runtimeCfg is nil, got %v", d)
	}
}

// _deadlineExceededBackend synthesises context.DeadlineExceeded on shutdown
// to exercise the library-bound suppression path. Other Backend methods
// promote from the embedded _fakeBackend.
type _deadlineExceededBackend struct{ _fakeBackend }

func (b *_deadlineExceededBackend) Shutdown(context.Context) error {
	return context.DeadlineExceeded
}

// _genericErrorBackend returns a non-deadline error to prove the suppression
// is narrowly scoped to context.DeadlineExceeded.
type _genericErrorBackend struct{ _fakeBackend }

func (b *_genericErrorBackend) Shutdown(context.Context) error {
	return errors.New("backend shutdown failed")
}

func TestShutdownTelemetry_SuppressesDeadlineExceededFromLibraryBound(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	// Library-bounded shutdown that abandons a still-pending flush must
	// return nil — matches the Python / TS / Rust contract that bounded
	// shutdown "returns cleanly even when records are dropped." Surface a
	// fake backend that synthesises context.DeadlineExceeded to prove the
	// suppression is wired without depending on real OTel timing.
	_, _ = RegisterBackend("deadline-test", &_deadlineExceededBackend{})
	t.Cleanup(func() { _, _ = UnregisterBackend("deadline-test") })

	t.Setenv("PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS", "0.05")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Errorf("library-bounded shutdown must swallow DeadlineExceeded, got %v", err)
	}
}

func TestShutdownTelemetry_SurfacesNonDeadlineErrorsFromBackend(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	// A non-deadline backend error must still propagate — the suppression
	// is narrow (context.DeadlineExceeded only).
	_, _ = RegisterBackend("backend-error", &_genericErrorBackend{})
	t.Cleanup(func() { _, _ = UnregisterBackend("backend-error") })

	t.Setenv("PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS", "0.05")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	err := ShutdownTelemetry(context.Background())
	if err == nil {
		t.Error("expected non-deadline backend error to propagate")
	}
}

func TestShutdownTelemetry_SurfacesCallerDeadlineExceeded(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	// When the caller supplies the deadline (not the library), surface
	// DeadlineExceeded as an error — the caller explicitly asked for that
	// bound and presumably wants to know it fired.
	_, _ = RegisterBackend("caller-deadline", &_deadlineExceededBackend{})
	t.Cleanup(func() { _, _ = UnregisterBackend("caller-deadline") })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	err := ShutdownTelemetry(ctx)
	if err == nil {
		t.Error("caller-supplied deadline must surface DeadlineExceeded")
	}
}

func TestShutdownTelemetry_DeadlineHelperReadsConfiguredTimeout(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS", "2.5")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	_setupMu.Lock()
	d := _shutdownDeadlineForLocked(context.Background())
	_setupMu.Unlock()
	want := 2500 * time.Millisecond
	if d != want {
		t.Errorf("expected %v from 2.5s config, got %v", want, d)
	}
}
