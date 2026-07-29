// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"errors"
	"log/slog"
	"testing"
	"time"
)

// _stubBackend satisfies Backend and nothing more — it deliberately has no
// ForceFlush, standing in for a third-party backend written before
// FlushableBackend existed.
type _stubBackend struct{}

func (b *_stubBackend) Setup(*TelemetryConfig, BackendSetupState) error { return nil }
func (b *_stubBackend) Shutdown(context.Context) error                  { return nil }
func (b *_stubBackend) ResetForTests()                                  {}
func (b *_stubBackend) Providers() SignalStatus                         { return SignalStatus{} }
func (b *_stubBackend) Tracer(string) Tracer                            { return nil }
func (b *_stubBackend) TraceContext(context.Context) (string, string, bool) {
	return "", "", false
}
func (b *_stubBackend) LoggerHandler(string) slog.Handler { return nil }
func (b *_stubBackend) Meter(string) any                  { return nil }
func (b *_stubBackend) NewCounter(string, InstrumentOptions) (Counter, bool) {
	return nil, false
}
func (b *_stubBackend) NewGauge(string, InstrumentOptions) (Gauge, bool) { return nil, false }
func (b *_stubBackend) NewHistogram(string, InstrumentOptions) (Histogram, bool) {
	return nil, false
}

// _flushBackend records ForceFlush calls and can fail on demand.
type _flushBackend struct {
	_stubBackend
	flushes int
	err     error
}

func (b *_flushBackend) ForceFlush(context.Context) error {
	b.flushes++
	return b.err
}

func registerFlushBackend(t *testing.T, b Backend) {
	t.Helper()
	RegisterBackend("test-flush", b)
	t.Cleanup(func() { UnregisterBackend("test-flush") })
}

func setupDone() bool {
	_setupMu.Lock()
	defer _setupMu.Unlock()
	return _setupDone
}

func TestFlushTelemetry_IsANoopBeforeSetup(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	backend := &_flushBackend{}
	registerFlushBackend(t, backend)

	if err := FlushTelemetry(context.Background()); err != nil {
		t.Fatalf("flush before setup returned %v, want nil", err)
	}
	if backend.flushes != 0 {
		t.Errorf("flushed %d times before setup, want 0", backend.flushes)
	}
}

func TestFlushTelemetry_DrainsTheBackendAndLeavesItInstalled(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	backend := &_flushBackend{}
	registerFlushBackend(t, backend)
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	if err := FlushTelemetry(context.Background()); err != nil {
		t.Fatalf("flush returned %v, want nil", err)
	}
	// Still installed: a second flush must reach the same backend.
	if err := FlushTelemetry(context.Background()); err != nil {
		t.Fatalf("second flush returned %v, want nil", err)
	}
	if backend.flushes != 2 {
		t.Errorf("flushed %d times, want 2", backend.flushes)
	}
	if !setupDone() {
		t.Error("flush tore telemetry down; it must leave it usable")
	}
}

func TestFlushTelemetry_SurfacesBackendError(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	want := errors.New("exporter down")
	registerFlushBackend(t, &_flushBackend{err: want})
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	if err := FlushTelemetry(context.Background()); !errors.Is(err, want) {
		t.Fatalf("flush returned %v, want %v", err, want)
	}
}

func TestFlushTelemetry_DoesNotSuppressAnExpiredDeadline(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	// Unlike ShutdownTelemetry, a caller flushing to be sure its records are
	// out must learn when they are not.
	registerFlushBackend(t, &_flushBackend{err: context.DeadlineExceeded})
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	if err := FlushTelemetry(context.Background()); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("flush returned %v, want context.DeadlineExceeded", err)
	}
}

func TestFlushTelemetry_AppliesBoundedDeadlineWhenCtxHasNone(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS", "0.05")
	seen := make(chan bool, 1)
	registerFlushBackend(t, &_deadlineProbeBackend{seen: seen})
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	if err := FlushTelemetry(context.Background()); err != nil {
		t.Fatalf("flush returned %v, want nil", err)
	}
	if hadDeadline := <-seen; !hadDeadline {
		t.Error("flush passed a context with no deadline; the library bound must be applied")
	}
}

func TestFlushTelemetry_HonoursCallerDeadline(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS", "30")
	seen := make(chan time.Duration, 1)
	registerFlushBackend(t, &_deadlineDurationBackend{seen: seen})
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 40*time.Millisecond)
	defer cancel()
	if err := FlushTelemetry(ctx); err != nil {
		t.Fatalf("flush returned %v, want nil", err)
	}
	if remaining := <-seen; remaining > time.Second {
		t.Errorf("caller deadline was overwritten: %v remaining, want the caller's ~40ms", remaining)
	}
}

func TestFlushTelemetry_IsANoopForABackendThatCannotFlush(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	registerFlushBackend(t, &_stubBackend{})
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	if err := FlushTelemetry(context.Background()); err != nil {
		t.Fatalf("flush returned %v, want nil for a backend without ForceFlush", err)
	}
}

func TestFlushTelemetry_IsANoopWithNoBackendRegistered(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	if err := FlushTelemetry(context.Background()); err != nil {
		t.Fatalf("flush returned %v, want nil with no backend", err)
	}
}

// ── deadline probes ───────────────────────────────────────────────────

type _deadlineProbeBackend struct {
	_stubBackend
	seen chan bool
}

func (b *_deadlineProbeBackend) ForceFlush(ctx context.Context) error {
	_, ok := ctx.Deadline()
	b.seen <- ok
	return nil
}

type _deadlineDurationBackend struct {
	_stubBackend
	seen chan time.Duration
}

func (b *_deadlineDurationBackend) ForceFlush(ctx context.Context) error {
	deadline, ok := ctx.Deadline()
	if !ok {
		b.seen <- time.Hour
		return nil
	}
	b.seen <- time.Until(deadline)
	return nil
}
