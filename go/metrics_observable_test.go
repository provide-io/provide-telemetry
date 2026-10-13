// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"log/slog"
	"testing"
)

// _fakeObservableBackend records what NewObservable was asked for.
type _fakeObservableBackend struct {
	*_fakeBackend
	accept      bool
	kinds       []ObservableKind
	opts        []InstrumentOptions
	callbacks   []ObservableCallback
	unregisters int
}

func (b *_fakeObservableBackend) NewObservable(kind ObservableKind, _ string, opts InstrumentOptions, cb ObservableCallback) (func(), bool) {
	b.kinds = append(b.kinds, kind)
	b.opts = append(b.opts, opts)
	b.callbacks = append(b.callbacks, cb)
	return func() { b.unregisters++ }, b.accept
}

func _withObservableBackend(t *testing.T, accept bool) *_fakeObservableBackend {
	t.Helper()
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	backend := &_fakeObservableBackend{_fakeBackend: &_fakeBackend{}, accept: accept}
	RegisterBackend("fake-observable", backend)
	t.Cleanup(func() { UnregisterBackend("fake-observable") })
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatal(err)
	}
	return backend
}

func TestObservable_WithoutBackendIsANoOp(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	called := false
	reg := NewObservableGauge("noop.gauge", func(context.Context) []Observation { called = true; return nil })
	reg.Unregister()
	reg.Unregister()
	if called {
		t.Fatal("without a backend the callback must never run")
	}
}

func TestObservable_BackendReceivesKindOptionsAndUnregister(t *testing.T) {
	backend := _withObservableBackend(t, true)
	cb := func(context.Context) []Observation { return nil }
	regs := []interface{ Unregister() }{
		NewObservableCounter("c", cb, WithUnit("s")),
		NewObservableGauge("g", cb, WithDescription("gauge")),
		NewObservableUpDownCounter("u", cb),
	}
	want := []ObservableKind{ObservableKindCounter, ObservableKindGauge, ObservableKindUpDownCounter}
	for i, k := range want {
		if backend.kinds[i] != k {
			t.Fatalf("kind %d = %v, want %v", i, backend.kinds[i], k)
		}
	}
	if backend.opts[0].Unit != "s" || backend.opts[1].Description != "gauge" {
		t.Fatalf("options not passed: %+v", backend.opts)
	}
	regs[0].Unregister()
	regs[0].Unregister()
	if backend.unregisters != 1 {
		t.Fatalf("unregister ran %d times, want exactly 1", backend.unregisters)
	}
}

func TestObservable_RefusedByBackendFallsBackToNoOp(t *testing.T) {
	backend := _withObservableBackend(t, false)
	NewObservableCounter("refused", func(context.Context) []Observation { return nil }).Unregister()
	if backend.unregisters != 0 {
		t.Fatal("a refused registration must not call the backend's unregister")
	}
}

func TestObservable_GatedCallbackPassesObservationsAndCountsThem(t *testing.T) {
	backend := _withObservableBackend(t, true)
	NewObservableGauge("gated", func(context.Context) []Observation {
		return []Observation{{Value: 1}, {Value: 2, Attrs: []slog.Attr{slog.String("k", "v")}}}
	})
	before := GetHealthSnapshot().MetricsEmitted
	got := backend.callbacks[0](context.Background())
	if len(got) != 2 || got[1].Value != 2 {
		t.Fatalf("observations = %+v", got)
	}
	if after := GetHealthSnapshot().MetricsEmitted; after-before != 2 {
		t.Fatalf("MetricsEmitted grew by %d, want 2", after-before)
	}
}

func TestObservable_GatesSuppressObservations(t *testing.T) {
	backend := _withObservableBackend(t, true)
	NewObservableGauge("gated", func(context.Context) []Observation { return []Observation{{Value: 1}} })
	NewObservableGauge("nil-callback", nil)
	if got := backend.callbacks[1](context.Background()); got != nil {
		t.Fatalf("a nil callback must report nothing, got %v", got)
	}
	_metricsGate.Set(false)
	if got := backend.callbacks[0](context.Background()); got != nil {
		t.Fatalf("metrics disabled must report nothing, got %v", got)
	}
	_metricsGate.Set(true)
	SetConsentLevel(ConsentNone)
	t.Cleanup(func() { SetConsentLevel(ConsentFull) })
	if got := backend.callbacks[0](context.Background()); got != nil {
		t.Fatalf("consent NONE must report nothing, got %v", got)
	}
}

func TestObservable_PanicIsRecovered(t *testing.T) {
	backend := _withObservableBackend(t, true)
	NewObservableCounter("panics", func(context.Context) []Observation { panic("boom") })
	for i := 0; i < 2; i++ { // the second panic exercises the warn-once guard
		if got := backend.callbacks[0](context.Background()); got != nil {
			t.Fatalf("a panicking callback must report nothing, got %v", got)
		}
	}
	resetSetupState(t) // no logger: a panic must still be recovered
	if got := backend.callbacks[0](context.Background()); got != nil {
		t.Fatalf("got %v", got)
	}
}
