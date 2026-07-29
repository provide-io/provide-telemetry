// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"testing"

	telemetry "github.com/provide-io/provide-telemetry/go"
	"go.opentelemetry.io/otel"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
)

func adoptConfig() *telemetry.TelemetryConfig {
	cfg := telemetry.DefaultTelemetryConfig()
	cfg.Tracing.Enabled = true
	cfg.Metrics.Enabled = true
	return cfg
}

// A host application's SDK owning the globals must be emitted through, not
// ignored — parity with the Python and TypeScript facades, which resolve their
// tracer off the global and have always honoured a foreign provider.
func TestAdopt_UsesAHostInstalledTracerProvider(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	hostTP, exp := newInMemoryTP()
	otel.SetTracerProvider(hostTP)

	backend := &_backend{}
	if err := backend.Setup(adoptConfig(), telemetry.BackendSetupState{}); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	if !backend.Providers().Traces {
		t.Fatal("providers.traces is false while a host provider owns the global")
	}
	tracer := backend.Tracer("adopt.test")
	if tracer == nil {
		t.Fatal("Tracer() returned nil with a host provider installed")
	}
	_, span := tracer.Start(context.Background(), "adopt.span")
	span.End()

	if got := len(exp.GetSpans()); got != 1 {
		t.Fatalf("host exporter received %d spans, want 1", got)
	}
}

func TestAdopt_UsesAHostInstalledMeterProvider(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	reader := sdkmetric.NewManualReader()
	otel.SetMeterProvider(sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader)))

	backend := &_backend{}
	if err := backend.Setup(adoptConfig(), telemetry.BackendSetupState{}); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	if !backend.Providers().Metrics {
		t.Fatal("providers.metrics is false while a host provider owns the global")
	}
	if backend.Meter("adopt.test") == nil {
		t.Fatal("Meter() returned nil with a host provider installed")
	}
	if _, ok := backend.NewCounter("adopt.counter", telemetry.InstrumentOptions{}); !ok {
		t.Fatal("NewCounter failed with a host provider installed")
	}
}

// Our own provider must win: adoption runs last and only fills empty signals.
func TestAdopt_OurOwnProviderTakesPrecedence(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	hostTP, hostExp := newInMemoryTP()
	otel.SetTracerProvider(hostTP)

	ourTP, ourExp := newInMemoryTP()
	backend := &_backend{}
	if err := backend.Setup(adoptConfig(), telemetry.BackendSetupState{}); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	// Simulate our own install winning the signal while the host's still owns
	// the global — ours must be preferred.
	_otelTracerProvider = ourTP

	_, span := backend.Tracer("precedence").Start(context.Background(), "ours")
	span.End()

	if len(ourExp.GetSpans()) != 1 || len(hostExp.GetSpans()) != 0 {
		t.Fatalf("span went to the wrong provider: ours=%d host=%d",
			len(ourExp.GetSpans()), len(hostExp.GetSpans()))
	}
}

// Shutting our telemetry down must not shut down the host's SDK.
func TestAdopt_ShutdownLeavesTheHostProviderAlive(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	hostTP, exp := newInMemoryTP()
	otel.SetTracerProvider(hostTP)

	backend := &_backend{}
	if err := backend.Setup(adoptConfig(), telemetry.BackendSetupState{}); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	if err := backend.Shutdown(context.Background()); err != nil {
		t.Fatalf("shutdown failed: %v", err)
	}

	// A shut-down SDK provider drops spans; the host's must still record.
	_, span := hostTP.Tracer("host").Start(context.Background(), "after.our.shutdown")
	span.End()
	if got := len(exp.GetSpans()); got != 1 {
		t.Fatalf("host provider recorded %d spans after our shutdown, want 1 — we tore down someone else's SDK", got)
	}
	if backend.Providers().Traces {
		t.Error("providers.traces still true after shutdown; the adopted provider was not released")
	}
}

func TestAdopt_IgnoresTheDelegatingGlobalPlaceholder(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	// resetSetupState leaves the API's no-op providers on the globals; those
	// carry no ForceFlush/Shutdown pair and must not be adopted.
	backend := &_backend{}
	if err := backend.Setup(adoptConfig(), telemetry.BackendSetupState{}); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	if backend.Providers().Traces || backend.Providers().Metrics {
		t.Error("adopted a placeholder provider; only live SDK providers may be adopted")
	}
}

func TestAdopt_SkipsDisabledSignals(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	hostTP, _ := newInMemoryTP()
	otel.SetTracerProvider(hostTP)

	cfg := adoptConfig()
	cfg.Tracing.Enabled = false
	cfg.Metrics.Enabled = false

	backend := &_backend{}
	if err := backend.Setup(cfg, telemetry.BackendSetupState{}); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	if backend.Providers().Traces {
		t.Error("adopted a tracer provider for a disabled signal")
	}
}

func TestIsLiveProvider_RequiresBothLifecycleMethods(t *testing.T) {
	cases := []struct {
		name string
		p    any
		want bool
	}{
		{"neither", struct{}{}, false},
		{"flush only", _flushOnlyProvider{}, false},
		{"shutdown only", _shutdownOnlyProvider{}, false},
		{"both", _lifecycleProvider{}, true},
	}
	for _, tc := range cases {
		if got := _isLiveProvider(tc.p); got != tc.want {
			t.Errorf("%s: _isLiveProvider = %v, want %v", tc.name, got, tc.want)
		}
	}
}

type _flushOnlyProvider struct{}

func (_flushOnlyProvider) ForceFlush(context.Context) error { return nil }

type _shutdownOnlyProvider struct{}

func (_shutdownOnlyProvider) Shutdown(context.Context) error { return nil }

type _lifecycleProvider struct{}

func (_lifecycleProvider) ForceFlush(context.Context) error { return nil }
func (_lifecycleProvider) Shutdown(context.Context) error   { return nil }

// A host that registers its SDK *after* our setup — an auto-instrumentation
// agent, a lazily-initialised vendor distro — must still be honoured. A
// setup-time snapshot would miss it forever.
func TestAdopt_PicksUpAProviderRegisteredAfterSetup(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	backend := &_backend{}
	if err := backend.Setup(adoptConfig(), telemetry.BackendSetupState{}); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	if backend.Providers().Traces {
		t.Fatal("nothing is installed yet; traces must not report a provider")
	}

	// The host boots its SDK now, after we are already set up.
	hostTP, exp := newInMemoryTP()
	otel.SetTracerProvider(hostTP)

	if !backend.Providers().Traces {
		t.Fatal("a provider registered after setup was not picked up")
	}
	_, span := backend.Tracer("late").Start(context.Background(), "late.span")
	span.End()
	if got := len(exp.GetSpans()); got != 1 {
		t.Fatalf("host exporter received %d spans, want 1", got)
	}
}

// Our shutdown must not switch off a host's instrumentation by clobbering the
// global registration it depends on.
func TestShutdown_LeavesAHostsGlobalRegistrationIntact(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	hostTP, exp := newInMemoryTP()
	otel.SetTracerProvider(hostTP)

	backend := &_backend{}
	if err := backend.Setup(adoptConfig(), telemetry.BackendSetupState{}); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	if err := backend.Shutdown(context.Background()); err != nil {
		t.Fatalf("shutdown failed: %v", err)
	}

	// The host's own instrumentation reaches for the global, not its handle.
	_, span := otel.GetTracerProvider().Tracer("host").Start(context.Background(), "after.our.shutdown")
	span.End()
	if got := len(exp.GetSpans()); got != 1 {
		t.Fatalf("host recorded %d spans through the global after our shutdown, want 1", got)
	}
}
