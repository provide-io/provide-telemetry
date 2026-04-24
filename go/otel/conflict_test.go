// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"bytes"
	"context"
	"log/slog"
	"strings"
	"testing"

	telemetry "github.com/provide-io/provide-telemetry/go"
	"go.opentelemetry.io/otel"
	logglobal "go.opentelemetry.io/otel/log/global"
	otellognoop "go.opentelemetry.io/otel/log/noop"
	otelmetricnoop "go.opentelemetry.io/otel/metric/noop"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
	otelnooptrace "go.opentelemetry.io/otel/trace/noop"
)

type captureHandler struct {
	buf *bytes.Buffer
	lvl slog.Level
}

func newCaptureHandler(lvl slog.Level) *captureHandler {
	return &captureHandler{buf: &bytes.Buffer{}, lvl: lvl}
}

func (h *captureHandler) Enabled(_ context.Context, level slog.Level) bool { return level >= h.lvl }
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

type _thirdPartyTracerProvider struct {
	otelnooptrace.TracerProvider
}

type _thirdPartyMeterProvider struct {
	otelmetricnoop.MeterProvider
}

type _globalDelegatingMeterProvider struct {
	otelmetricnoop.MeterProvider
}

type _thirdPartyLoggerProvider struct {
	otellognoop.LoggerProvider
}

type _globalDelegatingLoggerProvider struct {
	otellognoop.LoggerProvider
}

func resetOTelGlobal(t *testing.T) {
	t.Helper()
	tp := sdktrace.NewTracerProvider()
	otel.SetTracerProvider(tp)
	_ = tp.Shutdown(context.Background())

	mp := sdkmetric.NewMeterProvider()
	otel.SetMeterProvider(mp)
	_ = mp.Shutdown(context.Background())

	logglobal.SetLoggerProvider(otellognoop.NewLoggerProvider())
}

func TestWarnIfTracerProviderConflict_NoWarnForDefaultGlobal(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() {
		resetOTelGlobal(t)
		resetSetupState(t)
	})

	h := newCaptureHandler(slog.LevelWarn)
	telemetry.Logger = slog.New(h)

	_warnIfTracerProviderConflict()

	if strings.Contains(h.buf.String(), "conflict") {
		t.Fatalf("unexpected conflict warning for default global: %s", h.buf.String())
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
	telemetry.Logger = slog.New(h)

	_warnIfTracerProviderConflict()

	if strings.Contains(h.buf.String(), "conflict") {
		t.Fatalf("unexpected conflict warning for own SDK provider: %s", h.buf.String())
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
	telemetry.Logger = slog.New(h)

	_warnIfTracerProviderConflict()

	if !strings.Contains(h.buf.String(), "otel.tracer_provider_conflict") {
		t.Fatalf("expected tracer conflict warning, got %q", h.buf.String())
	}
}

func TestWarnIfTracerProviderConflict_NoWarnWhenProviderAlreadyOwned(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() {
		resetOTelGlobal(t)
		resetSetupState(t)
	})

	otel.SetTracerProvider(&_thirdPartyTracerProvider{})
	exp := tracetest.NewInMemoryExporter()
	_otelTracerProvider = sdktrace.NewTracerProvider(sdktrace.WithSyncer(exp))
	t.Cleanup(func() { _ = _otelTracerProvider.Shutdown(context.Background()) })

	h := newCaptureHandler(slog.LevelWarn)
	telemetry.Logger = slog.New(h)

	_warnIfTracerProviderConflict()

	if strings.Contains(h.buf.String(), "conflict") {
		t.Fatalf("unexpected conflict warning when provider already owned: %s", h.buf.String())
	}
}

func TestWarnIfMeterProviderConflict_RecognisesDefaultAndThirdParty(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() {
		resetOTelGlobal(t)
		resetSetupState(t)
	})

	otel.SetMeterProvider(&_globalDelegatingMeterProvider{})
	h := newCaptureHandler(slog.LevelWarn)
	telemetry.Logger = slog.New(h)
	_warnIfMeterProviderConflict()
	if strings.Contains(h.buf.String(), "conflict") {
		t.Fatalf("unexpected conflict warning for global meter provider: %s", h.buf.String())
	}

	otel.SetMeterProvider(&_thirdPartyMeterProvider{})
	_warnIfMeterProviderConflict()
	if !strings.Contains(h.buf.String(), "otel.meter_provider_conflict") {
		t.Fatalf("expected meter conflict warning, got %q", h.buf.String())
	}
}

func TestWarnIfMeterProviderConflict_NoWarnWhenProviderAlreadyOwned(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() {
		resetOTelGlobal(t)
		resetSetupState(t)
	})

	otel.SetMeterProvider(&_thirdPartyMeterProvider{})
	_otelMeterProvider = sdkmetric.NewMeterProvider()
	t.Cleanup(func() { _ = _otelMeterProvider.Shutdown(context.Background()) })

	h := newCaptureHandler(slog.LevelWarn)
	telemetry.Logger = slog.New(h)
	_warnIfMeterProviderConflict()

	if strings.Contains(h.buf.String(), "conflict") {
		t.Fatalf("unexpected conflict warning when meter already owned: %s", h.buf.String())
	}
}

func TestWarnIfLoggerProviderConflict_RecognisesDefaultAndThirdParty(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() {
		resetOTelGlobal(t)
		resetSetupState(t)
	})

	logglobal.SetLoggerProvider(&_globalDelegatingLoggerProvider{})
	h := newCaptureHandler(slog.LevelWarn)
	telemetry.Logger = slog.New(h)
	_warnIfLoggerProviderConflict()
	if strings.Contains(h.buf.String(), "conflict") {
		t.Fatalf("unexpected conflict warning for global logger provider: %s", h.buf.String())
	}

	logglobal.SetLoggerProvider(&_thirdPartyLoggerProvider{})
	_warnIfLoggerProviderConflict()
	if !strings.Contains(h.buf.String(), "otel.logger_provider_conflict") {
		t.Fatalf("expected logger conflict warning, got %q", h.buf.String())
	}
}

func TestWarnIfLoggerProviderConflict_NoWarnWhenProviderAlreadyOwned(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() {
		resetOTelGlobal(t)
		resetSetupState(t)
	})

	logglobal.SetLoggerProvider(&_thirdPartyLoggerProvider{})
	_otelLoggerProvider = sdklog.NewLoggerProvider()
	t.Cleanup(func() { _ = _otelLoggerProvider.Shutdown(context.Background()) })

	h := newCaptureHandler(slog.LevelWarn)
	telemetry.Logger = slog.New(h)
	_warnIfLoggerProviderConflict()

	if strings.Contains(h.buf.String(), "conflict") {
		t.Fatalf("unexpected conflict warning when logger already owned: %s", h.buf.String())
	}
}

func TestWarnConflictHelpers_NoLogger_NoPanic(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() {
		resetOTelGlobal(t)
		resetSetupState(t)
	})

	telemetry.Logger = nil
	otel.SetTracerProvider(&_thirdPartyTracerProvider{})
	otel.SetMeterProvider(&_thirdPartyMeterProvider{})
	logglobal.SetLoggerProvider(&_thirdPartyLoggerProvider{})

	_warnIfTracerProviderConflict()
	_warnIfMeterProviderConflict()
	_warnIfLoggerProviderConflict()
}
