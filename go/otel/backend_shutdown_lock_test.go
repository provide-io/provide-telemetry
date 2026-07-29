// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"errors"
	"testing"
	"time"

	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

// _blockingProcessor stalls inside Shutdown until released, standing in for an
// exporter draining against an unreachable collector.
type _blockingProcessor struct {
	entered chan struct{}
	release chan struct{}
}

func (p *_blockingProcessor) OnStart(context.Context, sdktrace.ReadWriteSpan) {}
func (p *_blockingProcessor) OnEnd(sdktrace.ReadOnlySpan)                     {}
func (p *_blockingProcessor) ForceFlush(context.Context) error                { return nil }

func (p *_blockingProcessor) Shutdown(context.Context) error {
	close(p.entered)
	<-p.release
	return nil
}

// Shutdown must detach the providers under _providersMu and drain them outside
// it. Holding the write lock across the drain blocks every RLock reader — a
// concurrent FlushTelemetry resolving providers, Providers(), LoggerHandler —
// on a mutex no context deadline can bound, so an in-flight request hangs for
// the whole shutdown.
func TestShutdown_DoesNotHoldTheProviderLockWhileDraining(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	proc := &_blockingProcessor{entered: make(chan struct{}), release: make(chan struct{})}
	_otelTracerProvider = sdktrace.NewTracerProvider(sdktrace.WithSpanProcessor(proc))

	backend := &_backend{}
	shutdownDone := make(chan error, 1)
	go func() { shutdownDone <- backend.Shutdown(context.Background()) }()

	<-proc.entered

	readDone := make(chan struct{})
	go func() {
		backend.Providers()
		close(readDone)
	}()

	select {
	case <-readDone:
	case <-time.After(5 * time.Second):
		close(proc.release)
		t.Fatal("Providers() blocked on _providersMu while Shutdown was draining a stalled exporter")
	}

	close(proc.release)
	if err := <-shutdownDone; err != nil {
		t.Fatalf("shutdown returned %v, want nil", err)
	}
}

// FlushTelemetry's godoc promises an expired deadline reaches the caller as
// context.DeadlineExceeded, which invites `err == context.DeadlineExceeded`.
// errors.Join wraps even a single error, so a lone failure must be handed back
// untouched.
func TestJoinFlushErrors_ReturnsALoneErrorUnwrapped(t *testing.T) {
	err := _joinFlushErrors([]error{nil, context.DeadlineExceeded, nil})
	if err != context.DeadlineExceeded { //nolint:errorlint // identity is the contract under test
		t.Fatalf("got %#v, want the context.DeadlineExceeded value itself", err)
	}
}

func TestJoinFlushErrors_JoinsWhenMoreThanOneSignalFails(t *testing.T) {
	first := errors.New("traces down")
	second := errors.New("metrics down")

	err := _joinFlushErrors([]error{first, second})
	if !errors.Is(err, first) || !errors.Is(err, second) {
		t.Fatalf("got %v, want both errors reachable via errors.Is", err)
	}
	if err == first || err == second { //nolint:errorlint // asserting it is NOT either lone error
		t.Fatal("two failures collapsed to one error; the other was lost")
	}
}

func TestJoinFlushErrors_ReturnsNilWhenEverySignalSucceeded(t *testing.T) {
	if err := _joinFlushErrors([]error{nil, nil, nil}); err != nil {
		t.Fatalf("got %v, want nil", err)
	}
	if err := _joinFlushErrors(nil); err != nil {
		t.Fatalf("got %v, want nil for no providers at all", err)
	}
}
