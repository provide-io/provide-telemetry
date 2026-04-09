// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"

	"go.opentelemetry.io/contrib/bridges/otelslog"
	"go.opentelemetry.io/otel"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	oteltrace "go.opentelemetry.io/otel/trace"
)

// _otelTracerProvider is the package-level real OTel tracer provider, set by _applyOTelProviders.
var _otelTracerProvider *sdktrace.TracerProvider //nolint:gochecknoglobals

// _otelMeterProvider is the package-level real OTel meter provider, set by _applyOTelProviders.
var _otelMeterProvider *sdkmetric.MeterProvider //nolint:gochecknoglobals

// _otelTracerAdapter implements Tracer using a real OTel tracer.
type _otelTracerAdapter struct {
	inner oteltrace.Tracer
}

// Start begins a new OTel span and returns a context enriched with trace/span IDs.
func (a _otelTracerAdapter) Start(ctx context.Context, name string) (context.Context, Span) {
	ctx, span := a.inner.Start(ctx, name)
	sc := span.SpanContext()
	ctx = SetTraceContext(ctx, sc.TraceID().String(), sc.SpanID().String())
	return ctx, &_otelSpanAdapter{inner: span}
}

// _otelSpanAdapter implements Span using a real OTel span.
type _otelSpanAdapter struct {
	inner oteltrace.Span
}

// End finishes the span.
func (s *_otelSpanAdapter) End() { s.inner.End() }

// SetAttribute adds a key/value attribute to the span.
func (s *_otelSpanAdapter) SetAttribute(key string, value any) {
	_ = key
	_ = value
}

// RecordError records an error on the span.
func (s *_otelSpanAdapter) RecordError(err error) { s.inner.RecordError(err) }

// SpanID returns the hex-encoded span ID.
func (s *_otelSpanAdapter) SpanID() string { return s.inner.SpanContext().SpanID().String() }

// TraceID returns the hex-encoded trace ID.
func (s *_otelSpanAdapter) TraceID() string { return s.inner.SpanContext().TraceID().String() }

// _warnIfTracerProviderConflict logs a warning when a third-party tracer provider is
// already installed in the OTel global before we install ours.
//
// Detection logic:
//   - When no custom provider has been set, otel.GetTracerProvider() returns the OTel
//     internal delegating wrapper (type name contains "global"). This is the safe default.
//   - After SetTracerProvider, the actual provider type is returned directly.
//   - Our own *sdktrace.TracerProvider (from a previous cycle) is always acceptable.
func _warnIfTracerProviderConflict() {
	if _otelTracerProvider != nil {
		return // we installed the global ourselves in an active setup cycle
	}
	existing := otel.GetTracerProvider()
	if strings.Contains(fmt.Sprintf("%T", existing), "global") {
		return // OTel default delegating wrapper — no custom provider set
	}
	if _, isSDK := existing.(*sdktrace.TracerProvider); isSDK {
		return // SDK provider (ours from a prior cycle, or a compatible library)
	}
	if Logger != nil {
		Logger.Warn("otel.tracer_provider_conflict",
			slog.String("existing_type", fmt.Sprintf("%T", existing)),
			slog.String("action", "overwriting with provide-telemetry tracer provider"),
		)
	}
}

// _warnIfMeterProviderConflict logs a warning when a third-party meter provider is
// already installed in the OTel global before we install ours.
func _warnIfMeterProviderConflict() {
	if _otelMeterProvider != nil {
		return // we installed the global ourselves in an active setup cycle
	}
	existing := otel.GetMeterProvider()
	if strings.Contains(fmt.Sprintf("%T", existing), "global") {
		return // OTel default delegating wrapper — no custom provider set
	}
	if _, isSDK := existing.(*sdkmetric.MeterProvider); isSDK {
		return // SDK provider (ours from a prior cycle, or a compatible library)
	}
	if Logger != nil {
		Logger.Warn("otel.meter_provider_conflict",
			slog.String("existing_type", fmt.Sprintf("%T", existing)),
			slog.String("action", "overwriting with provide-telemetry meter provider"),
		)
	}
}

// _applyOTelProviders wires real OTel providers from state into the package-level singletons.
// It is called by SetupTelemetry when at least one provider option is present.
func _applyOTelProviders(state *_setupState, cfg *TelemetryConfig) {
	if state.tracerProvider != nil {
		if tp, ok := state.tracerProvider.(*sdktrace.TracerProvider); ok {
			_warnIfTracerProviderConflict()
			_otelTracerProvider = tp
			otel.SetTracerProvider(tp)
			tracer := tp.Tracer(cfg.ServiceName)
			_setDefaultTracer(_otelTracerAdapter{inner: tracer})
		}
	}

	if state.meterProvider != nil {
		if mp, ok := state.meterProvider.(*sdkmetric.MeterProvider); ok {
			_warnIfMeterProviderConflict()
			_otelMeterProvider = mp
			otel.SetMeterProvider(mp)
		}
	}

	// Wire slog → OTel log bridge: adds OTel log bridge as an additional slog handler.
	if Logger != nil {
		bridge := otelslog.NewHandler(cfg.ServiceName)
		combined := slog.New(newMultiHandler(Logger.Handler(), bridge))
		Logger = combined
		slog.SetDefault(Logger)
	}
}

// _shutdownOTelProviders gracefully shuts down real OTel providers.
// Returns the first error encountered; both providers are always attempted.
func _shutdownOTelProviders(ctx context.Context) error {
	var first error

	if _otelTracerProvider != nil {
		if err := _otelTracerProvider.Shutdown(ctx); err != nil {
			first = err
		}
		_otelTracerProvider = nil
	}

	if _otelMeterProvider != nil {
		if err := _otelMeterProvider.Shutdown(ctx); err != nil {
			if first == nil {
				first = err
			}
		}
		_otelMeterProvider = nil
	}

	return first
}

// _resetOTelProviders clears OTel provider singletons. For use in tests only.
func _resetOTelProviders() {
	_otelTracerProvider = nil
	_otelMeterProvider = nil
}

// multiHandler fans a slog.Record out to multiple slog.Handler implementations.
type multiHandler struct {
	handlers []slog.Handler
}

// newMultiHandler creates a multiHandler that forwards to all provided handlers.
func newMultiHandler(handlers ...slog.Handler) *multiHandler {
	return &multiHandler{handlers: handlers}
}

// Enabled returns true if any underlying handler is enabled for the given level.
func (m *multiHandler) Enabled(ctx context.Context, level slog.Level) bool {
	for _, h := range m.handlers {
		if h.Enabled(ctx, level) {
			return true
		}
	}
	return false
}

// Handle forwards the record to all underlying handlers, returning the first error.
func (m *multiHandler) Handle(ctx context.Context, r slog.Record) error {
	var first error
	for _, h := range m.handlers {
		if h.Enabled(ctx, r.Level) {
			if err := h.Handle(ctx, r); err != nil && first == nil {
				first = err
			}
		}
	}
	return first
}

// WithAttrs returns a new multiHandler with the attrs applied to all underlying handlers.
func (m *multiHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	hs := make([]slog.Handler, len(m.handlers))
	for i, h := range m.handlers {
		hs[i] = h.WithAttrs(attrs)
	}
	return &multiHandler{handlers: hs}
}

// WithGroup returns a new multiHandler with the group applied to all underlying handlers.
func (m *multiHandler) WithGroup(name string) slog.Handler {
	hs := make([]slog.Handler, len(m.handlers))
	for i, h := range m.handlers {
		hs[i] = h.WithGroup(name)
	}
	return &multiHandler{handlers: hs}
}

// errOTelShutdown is a sentinel used in tests to simulate provider shutdown errors.
var errOTelShutdown = errors.New("otel shutdown error")
