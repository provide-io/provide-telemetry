// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"context"
	"log/slog"
	"strings"
	"testing"

	"go.opentelemetry.io/otel"
	otelmetricnoop "go.opentelemetry.io/otel/metric/noop"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
	otelnooptrace "go.opentelemetry.io/otel/trace/noop"
)

// captureHandler collects slog records for inspection.
type captureHandler struct {
	buf *bytes.Buffer
	lvl slog.Level
}

func newCaptureHandler(lvl slog.Level) *captureHandler {
	return &captureHandler{buf: &bytes.Buffer{}, lvl: lvl}
}

func (h *captureHandler) Enabled(_ context.Context, l slog.Level) bool { return l >= h.lvl }
func (h *captureHandler) Handle(_ context.Context, r slog.Record) error {
	h.buf.WriteString(r.Message)
	r.Attrs(func(a slog.Attr) bool {
		h.buf.WriteString(" " + a.Key + "=" + a.Value.String())
		return true
	})
	h.buf.WriteByte('\n')
	return nil
}
func (h *captureHandler) WithAttrs(_ []slog.Attr) slog.Handler { return h }
func (h *captureHandler) WithGroup(_ string) slog.Handler      { return h }

// _thirdPartyTracerProvider satisfies oteltrace.TracerProvider by embedding the noop
// (which carries the private tracerProvider() method). Its type name does NOT contain
// "global" or "sdk", simulating a genuinely unknown third-party provider.
type _thirdPartyTracerProvider struct {
	otelnooptrace.TracerProvider
}

// _thirdPartyMeterProvider satisfies otelmetric.MeterProvider by embedding the noop.
type _thirdPartyMeterProvider struct {
	otelmetricnoop.MeterProvider
}

// _globalDelegatingMeterProvider simulates OTel's own internal global delegating wrapper.
// Its type name contains "global", so _warnIfMeterProviderConflict treats it as non-conflicting.
type _globalDelegatingMeterProvider struct {
	otelmetricnoop.MeterProvider
}

// resetOTelGlobal restores the OTel global tracer/meter to an SDK noop state so
// subsequent tests start from a known "no third-party conflict" baseline.
// Because otel.SetTracerProvider has no "undo", we install an SDK provider that
// _warnIfTracerProviderConflict will correctly recognise as non-conflicting.
func resetOTelGlobal(t *testing.T) {
	t.Helper()
	tp := sdktrace.NewTracerProvider()
	otel.SetTracerProvider(tp)
	_ = tp.Shutdown(context.Background())

	mp := sdkmetric.NewMeterProvider()
	otel.SetMeterProvider(mp)
	_ = mp.Shutdown(context.Background())
}

// ── _warnIfTracerProviderConflict ─────────────────────────────────────────────

func TestWarnIfTracerProviderConflict_NoWarnForDefaultGlobal(t *testing.T) {
	// Ensure we start from default OTel global state (no custom provider).
	// The first test in the suite naturally starts in this state.
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	// Do NOT call otel.SetTracerProvider — global stays as the default delegating wrapper.
	h := newCaptureHandler(slog.LevelWarn)
	Logger = slog.New(h)

	_warnIfTracerProviderConflict()

	if strings.Contains(h.buf.String(), "conflict") {
		t.Errorf("unexpected conflict warning for default global: %s", h.buf.String())
	}
}

func TestWarnIfTracerProviderConflict_NoWarnForOwnSDKProvider(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() {
		resetOTelGlobal(t)
		resetSetupState(t)
	})

	exp := tracetest.NewInMemoryExporter()
	sdkTP := sdktrace.NewTracerProvider(sdktrace.WithSyncer(exp))
	t.Cleanup(func() { _ = sdkTP.Shutdown(context.Background()) })
	otel.SetTracerProvider(sdkTP)

	h := newCaptureHandler(slog.LevelWarn)
	Logger = slog.New(h)

	_warnIfTracerProviderConflict()

	if strings.Contains(h.buf.String(), "conflict") {
		t.Errorf("unexpected conflict warning for own SDK provider: %s", h.buf.String())
	}
}

func TestWarnIfTracerProviderConflict_NoWarnWhenOtelTracerProviderSet(t *testing.T) {
	// Simulate: we have an active provider in _otelTracerProvider.
	resetSetupState(t)
	t.Cleanup(func() {
		resetOTelGlobal(t)
		resetSetupState(t)
	})

	// Set a third-party provider globally AND mark _otelTracerProvider as if we set it.
	otel.SetTracerProvider(&_thirdPartyTracerProvider{})
	exp := tracetest.NewInMemoryExporter()
	_otelTracerProvider = sdktrace.NewTracerProvider(sdktrace.WithSyncer(exp))
	t.Cleanup(func() { _ = _otelTracerProvider.Shutdown(context.Background()) })

	h := newCaptureHandler(slog.LevelWarn)
	Logger = slog.New(h)

	_warnIfTracerProviderConflict()

	if strings.Contains(h.buf.String(), "conflict") {
		t.Errorf("unexpected conflict warning when _otelTracerProvider is set: %s", h.buf.String())
	}
}

func TestWarnIfTracerProviderConflict_WarnsForThirdParty(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() {
		resetOTelGlobal(t)
		resetSetupState(t)
	})

	otel.SetTracerProvider(&_thirdPartyTracerProvider{})

	h := newCaptureHandler(slog.LevelWarn)
	Logger = slog.New(h)

	_warnIfTracerProviderConflict()

	if !strings.Contains(h.buf.String(), "otel.tracer_provider_conflict") {
		t.Errorf("expected conflict warning for third-party provider, got: %q", h.buf.String())
	}
}

func TestWarnIfTracerProviderConflict_NoWarnWhenLoggerNil(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() {
		resetOTelGlobal(t)
		resetSetupState(t)
	})

	otel.SetTracerProvider(&_thirdPartyTracerProvider{})
	Logger = nil

	_warnIfTracerProviderConflict() // must not panic
}

// ── _warnIfMeterProviderConflict ─────────────────────────────────────────────

func TestWarnIfMeterProviderConflict_NoWarnForDefaultGlobal(t *testing.T) {
	// Install a provider whose type name contains "global" to simulate OTel's own
	// internal delegating wrapper. This makes the test self-contained rather than
	// relying on initial process state (which prior tests may have mutated).
	resetSetupState(t)
	t.Cleanup(func() {
		resetOTelGlobal(t)
		resetSetupState(t)
	})

	otel.SetMeterProvider(&_globalDelegatingMeterProvider{})
	h := newCaptureHandler(slog.LevelWarn)
	Logger = slog.New(h)

	_warnIfMeterProviderConflict()

	if strings.Contains(h.buf.String(), "conflict") {
		t.Errorf("unexpected conflict warning for global-named meter provider: %s", h.buf.String())
	}
}

func TestWarnIfMeterProviderConflict_NoWarnForOwnSDKProvider(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() {
		resetOTelGlobal(t)
		resetSetupState(t)
	})

	mp := sdkmetric.NewMeterProvider()
	t.Cleanup(func() { _ = mp.Shutdown(context.Background()) })
	otel.SetMeterProvider(mp)

	h := newCaptureHandler(slog.LevelWarn)
	Logger = slog.New(h)

	_warnIfMeterProviderConflict()

	if strings.Contains(h.buf.String(), "conflict") {
		t.Errorf("unexpected conflict warning for own SDK meter provider: %s", h.buf.String())
	}
}

func TestWarnIfMeterProviderConflict_NoWarnWhenOtelMeterProviderSet(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() {
		resetOTelGlobal(t)
		resetSetupState(t)
	})

	otel.SetMeterProvider(&_thirdPartyMeterProvider{})
	_otelMeterProvider = sdkmetric.NewMeterProvider()
	t.Cleanup(func() { _ = _otelMeterProvider.Shutdown(context.Background()) })

	h := newCaptureHandler(slog.LevelWarn)
	Logger = slog.New(h)

	_warnIfMeterProviderConflict()

	if strings.Contains(h.buf.String(), "conflict") {
		t.Errorf("unexpected conflict warning when _otelMeterProvider is set: %s", h.buf.String())
	}
}

func TestWarnIfMeterProviderConflict_WarnsForThirdParty(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() {
		resetOTelGlobal(t)
		resetSetupState(t)
	})

	otel.SetMeterProvider(&_thirdPartyMeterProvider{})

	h := newCaptureHandler(slog.LevelWarn)
	Logger = slog.New(h)

	_warnIfMeterProviderConflict()

	if !strings.Contains(h.buf.String(), "otel.meter_provider_conflict") {
		t.Errorf("expected conflict warning for third-party meter provider, got: %q", h.buf.String())
	}
}

func TestWarnIfMeterProviderConflict_NoWarnWhenLoggerNil(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() {
		resetOTelGlobal(t)
		resetSetupState(t)
	})

	otel.SetMeterProvider(&_thirdPartyMeterProvider{})
	Logger = nil

	_warnIfMeterProviderConflict() // must not panic
}
