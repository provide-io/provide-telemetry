// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"errors"
	"log/slog"
	"strings"
	"testing"
	"time"
)

type _recordingHandler struct {
	enabled bool
	err     error
	groups  []string
	handled int
}

func (h *_recordingHandler) Enabled(context.Context, slog.Level) bool { return h.enabled }

func (h *_recordingHandler) Handle(context.Context, slog.Record) error {
	h.handled++
	return h.err
}

func (h *_recordingHandler) WithAttrs([]slog.Attr) slog.Handler { return h }

func (h *_recordingHandler) WithGroup(name string) slog.Handler {
	cp := *h
	cp.groups = append(append([]string(nil), h.groups...), name)
	return &cp
}

type _erroringBackend struct {
	err error
}

func (b *_erroringBackend) Setup(*TelemetryConfig, BackendSetupState) error      { return b.err }
func (b *_erroringBackend) Shutdown(context.Context) error                       { return nil }
func (b *_erroringBackend) ResetForTests()                                       {}
func (b *_erroringBackend) Providers() SignalStatus                              { return SignalStatus{} }
func (b *_erroringBackend) Tracer(string) Tracer                                 { return nil }
func (b *_erroringBackend) TraceContext(context.Context) (string, string, bool)  { return "", "", false }
func (b *_erroringBackend) LoggerHandler(string) slog.Handler                    { return nil }
func (b *_erroringBackend) Meter(string) any                                     { return nil }
func (b *_erroringBackend) NewCounter(string, InstrumentOptions) (Counter, bool) { return nil, false }
func (b *_erroringBackend) NewGauge(string, InstrumentOptions) (Gauge, bool)     { return nil, false }
func (b *_erroringBackend) NewHistogram(string, InstrumentOptions) (Histogram, bool) {
	return nil, false
}

func TestHelperCoverage_BackendAndInstrumentHelpers(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	backend := &_fakeBackend{}
	previous, replaced := RegisterBackend("fake-helper", backend)
	t.Cleanup(func() {
		if replaced {
			RegisterBackend("fake-helper", previous)
			return
		}
		UnregisterBackend("fake-helper")
	})

	prevLogger := Logger
	Logger = nil
	t.Cleanup(func() { Logger = prevLogger })

	if err := _setupBackendLocked(&_setupState{}, DefaultTelemetryConfig()); err != nil {
		t.Fatalf("expected no backend setup error without provider config, got %v", err)
	}
	if backend.lastSetupCfg != nil {
		t.Fatal("expected backend.Setup to be skipped when no provider config or options are present")
	}

	var opts *_instrumentOptions
	if got := opts.snapshot(); got != (InstrumentOptions{}) {
		t.Fatalf("expected zero-value snapshot for nil instrument options, got %+v", got)
	}

	if hint := _providerImportHint("metrics"); !strings.Contains(hint, "metrics") || !strings.Contains(hint, "go/otel") {
		t.Fatalf("expected provider import hint to mention signal and backend import, got %q", hint)
	}
}

func TestHelperCoverage_SetupBackendLockedPropagatesBackendErrors(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	sentinel := errors.New("backend setup failed")
	previous, replaced := RegisterBackend("erroring-helper", &_erroringBackend{err: sentinel})
	t.Cleanup(func() {
		if replaced {
			RegisterBackend("erroring-helper", previous)
			return
		}
		UnregisterBackend("erroring-helper")
	})

	state := &_setupState{meterProvider: struct{}{}}
	if err := _setupBackendLocked(state, DefaultTelemetryConfig()); !errors.Is(err, sentinel) {
		t.Fatalf("expected backend setup error %v, got %v", sentinel, err)
	}
}

func TestHelperCoverage_MultiHandlerBranches(t *testing.T) {
	disabledA := &_recordingHandler{}
	disabledB := &_recordingHandler{}
	if newMultiHandler(disabledA, disabledB).Enabled(context.Background(), slog.LevelInfo) {
		t.Fatal("expected Enabled to be false when all handlers are disabled")
	}

	sentinel := errors.New("handler boom")
	enabled := &_recordingHandler{enabled: true, err: sentinel}
	mh := newMultiHandler(disabledA, enabled)
	if !mh.Enabled(context.Background(), slog.LevelInfo) {
		t.Fatal("expected Enabled to be true when any handler is enabled")
	}

	record := slog.NewRecord(time.Now(), slog.LevelInfo, "helper.coverage", 0)
	if err := mh.Handle(context.Background(), record); !errors.Is(err, sentinel) {
		t.Fatalf("expected first handler error %v, got %v", sentinel, err)
	}
	if disabledA.handled != 0 || enabled.handled != 1 {
		t.Fatalf("expected only enabled handler to receive record, got disabled=%d enabled=%d", disabledA.handled, enabled.handled)
	}

	grouped := mh.WithGroup("telemetry").(*multiHandler)
	got := grouped.handlers[1].(*_recordingHandler).groups
	if len(got) != 1 || got[0] != "telemetry" {
		t.Fatalf("expected group to be forwarded to handler, got %v", got)
	}
}

func TestHelperCoverage_SignalEndpointURLVariants(t *testing.T) {
	tests := []struct {
		name       string
		endpoint   string
		signalPath string
		want       string
	}{
		{name: "blank endpoint", endpoint: "   ", signalPath: "/v1/logs", want: ""},
		{name: "parsed endpoint appends path", endpoint: "http://collector:4318", signalPath: "/v1/logs", want: "http://collector:4318/v1/logs"},
		{name: "parsed endpoint extends existing path", endpoint: "http://collector:4318/base", signalPath: "/v1/logs", want: "http://collector:4318/base/v1/logs"},
		{name: "existing suffix preserved", endpoint: "http://collector:4318/v1/logs", signalPath: "/v1/logs", want: "http://collector:4318/v1/logs"},
		{name: "raw suffix preserved", endpoint: "collector:4318/v1/metrics", signalPath: "/v1/metrics", want: "collector:4318/v1/metrics"},
		{name: "raw endpoint appends path", endpoint: "collector:4318", signalPath: "/v1/metrics", want: "collector:4318/v1/metrics"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := _signalEndpointURL(tt.endpoint, tt.signalPath); got != tt.want {
				t.Fatalf("expected %q, got %q", tt.want, got)
			}
		})
	}
}
