// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"log/slog"
	"testing"
)

// _lateTracerBackend hands out a real tracer only once armed, standing in for a
// host SDK that registers itself after our setup has already run.
type _lateTracerBackend struct {
	_stubBackend
	armed  bool
	tracer Tracer
}

type _recordingTracer struct{ started []string }

func (t *_recordingTracer) Start(ctx context.Context, name string) (context.Context, Span) {
	t.started = append(t.started, name)
	return (&_noopTracer{}).Start(ctx, name)
}

func (b *_lateTracerBackend) Tracer(string) Tracer {
	if !b.armed {
		return nil
	}
	return b.tracer
}

func (b *_lateTracerBackend) LoggerHandler(string) slog.Handler { return nil }

func TestEffectiveTracer_ResolvesABackendTracerRegisteredAfterSetup(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	backend := &_lateTracerBackend{tracer: &_recordingTracer{}}
	RegisterBackend("test-late-tracer", backend)
	t.Cleanup(func() { UnregisterBackend("test-late-tracer") })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	// Nothing to bind at setup: the binding stays our no-op.
	if _, isNoop := DefaultTracer.(*_noopTracer); !isNoop {
		t.Fatalf("expected the no-op binding at setup, got %T", DefaultTracer)
	}

	// The host's SDK shows up now.
	backend.armed = true
	if got := _effectiveTracer(); got != backend.tracer {
		t.Fatalf("_effectiveTracer resolved %T, want the backend's late tracer", got)
	}
}

func TestEffectiveTracer_PrefersANonNoopBinding(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	bound := &_recordingTracer{}
	previous := DefaultTracer
	DefaultTracer = bound
	t.Cleanup(func() { DefaultTracer = previous })

	backend := &_lateTracerBackend{tracer: &_recordingTracer{}, armed: true}
	RegisterBackend("test-late-tracer", backend)
	t.Cleanup(func() { UnregisterBackend("test-late-tracer") })

	if got := _effectiveTracer(); got != bound {
		t.Fatalf("_effectiveTracer resolved %T, want the explicit binding", got)
	}
}

func TestEffectiveTracer_FallsBackToTheBindingWithoutABackend(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if got := _effectiveTracer(); got != DefaultTracer {
		t.Fatalf("_effectiveTracer resolved %T, want the DefaultTracer binding", got)
	}
}
