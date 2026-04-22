// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"log/slog"
	"testing"
)

type _fakeBackend struct {
	providers    SignalStatus
	shutdowns    int
	resets       int
	lastSetupCfg *TelemetryConfig
	logBody      []string
	counterAdds  []int64
	gaugeSets    []float64
	histRecords  []float64
	activeTrace  struct {
		traceID string
		spanID  string
	}
}

func (b *_fakeBackend) Setup(cfg *TelemetryConfig, state BackendSetupState) error {
	b.lastSetupCfg = cloneTelemetryConfig(cfg)
	b.providers = SignalStatus{
		Logs:    state.LoggerProvider() != nil || cfg.Logging.OTLPEndpoint != "",
		Traces:  state.TracerProvider() != nil || cfg.Tracing.OTLPEndpoint != "",
		Metrics: state.MeterProvider() != nil || cfg.Metrics.OTLPEndpoint != "",
	}
	b.activeTrace.traceID = "backend-trace-id"
	b.activeTrace.spanID = "backend-span-id"
	return nil
}

func (b *_fakeBackend) Shutdown(context.Context) error {
	b.shutdowns++
	b.providers = SignalStatus{}
	return nil
}

func (b *_fakeBackend) ResetForTests() {
	b.resets++
	b.providers = SignalStatus{}
	b.lastSetupCfg = nil
	b.logBody = nil
	b.counterAdds = nil
	b.gaugeSets = nil
	b.histRecords = nil
	b.activeTrace = struct {
		traceID string
		spanID  string
	}{}
}

func (b *_fakeBackend) Providers() SignalStatus { return b.providers }

func (b *_fakeBackend) Tracer(name string) Tracer {
	return &_fakeBackendTracer{name: name, backend: b}
}

func (b *_fakeBackend) TraceContext(ctx context.Context) (traceID, spanID string, ok bool) {
	if ctx == nil || b.activeTrace.traceID == "" || b.activeTrace.spanID == "" {
		return "", "", false
	}
	return b.activeTrace.traceID, b.activeTrace.spanID, true
}

func (b *_fakeBackend) LoggerHandler(name string) slog.Handler {
	return &_fakeBackendLogHandler{name: name, backend: b}
}

func (b *_fakeBackend) Meter(name string) any { return "meter:" + name }

func (b *_fakeBackend) NewCounter(name string, _ InstrumentOptions) (Counter, bool) {
	return &_fakeBackendCounter{name: name, backend: b}, true
}

func (b *_fakeBackend) NewGauge(name string, _ InstrumentOptions) (Gauge, bool) {
	return &_fakeBackendGauge{name: name, backend: b}, true
}

func (b *_fakeBackend) NewHistogram(name string, _ InstrumentOptions) (Histogram, bool) {
	return &_fakeBackendHistogram{name: name, backend: b}, true
}

type _fakeBackendTracer struct {
	name    string
	backend *_fakeBackend
}

func (t *_fakeBackendTracer) Start(ctx context.Context, name string) (context.Context, Span) {
	if ctx == nil {
		ctx = context.Background()
	}
	traceID := "trace:" + t.name + ":" + name
	spanID := "span:" + t.name + ":" + name
	t.backend.activeTrace.traceID = traceID
	t.backend.activeTrace.spanID = spanID
	return SetTraceContext(ctx, traceID, spanID), &_noopSpan{traceID: traceID, spanID: spanID}
}

type _fakeBackendLogHandler struct {
	name    string
	backend *_fakeBackend
}

func (h *_fakeBackendLogHandler) Enabled(context.Context, slog.Level) bool { return true }

func (h *_fakeBackendLogHandler) Handle(_ context.Context, record slog.Record) error {
	h.backend.logBody = append(h.backend.logBody, h.name+":"+record.Message)
	return nil
}

func (h *_fakeBackendLogHandler) WithAttrs([]slog.Attr) slog.Handler { return h }

func (h *_fakeBackendLogHandler) WithGroup(string) slog.Handler { return h }

type _fakeBackendCounter struct {
	name    string
	backend *_fakeBackend
}

func (c *_fakeBackendCounter) Add(_ context.Context, value int64, _ ...slog.Attr) {
	c.backend.counterAdds = append(c.backend.counterAdds, value)
}

type _fakeBackendGauge struct {
	name    string
	backend *_fakeBackend
}

func (g *_fakeBackendGauge) Set(_ context.Context, value float64, _ ...slog.Attr) {
	g.backend.gaugeSets = append(g.backend.gaugeSets, value)
}

type _fakeBackendHistogram struct {
	name    string
	backend *_fakeBackend
}

func (h *_fakeBackendHistogram) Record(_ context.Context, value float64, _ ...slog.Attr) {
	h.backend.histRecords = append(h.backend.histRecords, value)
}

func TestSetupTelemetryWithoutRegisteredBackendStaysInFallback(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")

	cfg, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}
	if cfg == nil {
		t.Fatal("expected non-nil config")
	}

	status := GetRuntimeStatus()
	if status.Providers.Logs || status.Providers.Traces || status.Providers.Metrics {
		t.Fatalf("expected no providers without optional backend, got %+v", status.Providers)
	}
	if !status.Fallback.Logs || !status.Fallback.Traces || !status.Fallback.Metrics {
		t.Fatalf("expected fallback mode without optional backend, got %+v", status.Fallback)
	}
	if _, ok := DefaultTracer.(*_noopTracer); !ok {
		t.Fatalf("expected noop tracer without optional backend, got %T", DefaultTracer)
	}
	if got := GetMeter("core.only"); got != nil {
		t.Fatalf("expected nil meter without optional backend, got %v", got)
	}
}

func TestSetupTelemetryProviderOptionsWithoutRegisteredBackendReturnsError(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(WithTracerProvider(struct{}{})); err == nil {
		t.Fatal("expected error when provider options are supplied without a registered backend")
	}
}

func TestRegisteredBackendDrivesTracingMetricsAndLogging(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	backend := &_fakeBackend{}
	previous, replaced := RegisterBackend("fake", backend)
	t.Cleanup(func() {
		if replaced {
			RegisterBackend("fake", previous)
		} else {
			UnregisterBackend("fake")
		}
	})

	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")

	cfg, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}
	if cfg == nil || backend.lastSetupCfg == nil {
		t.Fatal("expected backend to observe setup config")
	}

	status := GetRuntimeStatus()
	if !status.Providers.Logs || !status.Providers.Traces || !status.Providers.Metrics {
		t.Fatalf("expected backend-backed providers, got %+v", status.Providers)
	}
	if status.Fallback.Logs || status.Fallback.Traces || status.Fallback.Metrics {
		t.Fatalf("expected provider-backed runtime, got fallback %+v", status.Fallback)
	}

	ctx, span := GetTracer("fake.backend").Start(context.Background(), "backend-span")
	if span.TraceID() == "" || span.SpanID() == "" {
		t.Fatalf("expected backend-backed span IDs, got trace=%q span=%q", span.TraceID(), span.SpanID())
	}
	traceID, spanID := GetTraceContext(ctx)
	if traceID != span.TraceID() || spanID != span.SpanID() {
		t.Fatalf("expected backend trace context %q/%q, got %q/%q", span.TraceID(), span.SpanID(), traceID, spanID)
	}

	logger := GetLogger(ctx, "backend.logger")
	logger = slog.New(logger.Handler().WithAttrs([]slog.Attr{slog.String("source", "test")}))
	logger.Info("bridge")
	if len(backend.logBody) == 0 {
		t.Fatal("expected backend log bridge to capture a record")
	}

	counter := NewCounter("backend.counter")
	counter.Add(context.Background(), 7)
	if len(backend.counterAdds) != 1 || backend.counterAdds[0] != 7 {
		t.Fatalf("expected backend counter add of 7, got %v", backend.counterAdds)
	}
	if got := GetMeter("backend"); got != "meter:backend" {
		t.Fatalf("expected backend meter, got %v", got)
	}

	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("ShutdownTelemetry failed: %v", err)
	}
	if backend.shutdowns != 1 {
		t.Fatalf("expected backend shutdown once, got %d", backend.shutdowns)
	}
}

func TestResetForTestsResetsRegisteredBackends(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	backend := &_fakeBackend{}
	RegisterBackend("fake", backend)
	t.Cleanup(func() { UnregisterBackend("fake") })

	ResetForTests()

	if backend.resets == 0 {
		t.Fatal("expected ResetForTests to reset registered backends")
	}
}

func TestGetLoggerWithoutRegisteredBackendDoesNotRequireBridge(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	logger := GetLogger(context.Background(), "core.only")
	if logger == nil {
		t.Fatal("expected a logger without a registered backend")
	}
	logger.Info("core-only")
}
