// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"fmt"
	"log/slog"
	"strings"

	telemetry "github.com/provide-io/provide-telemetry/go"
	"go.opentelemetry.io/otel"
	logglobal "go.opentelemetry.io/otel/log/global"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

func _warnIfTracerProviderConflict() {
	if _otelTracerProvider != nil {
		return
	}
	existing := otel.GetTracerProvider()
	existingType := fmt.Sprintf("%T", existing)
	if strings.Contains(existingType, "global") || strings.Contains(existingType, "noop") {
		return
	}
	// No type-based suppression. This function is only reached when our own
	// provider field is nil — we have not installed anything — so a live
	// concrete provider on the global belongs to the host by definition, and a
	// host running the same SDK we do is the most likely real conflict, not the
	// least. Ownership is the evidence, not the type.
	if logger := telemetry.Logger(); logger != nil {
		logger.Warn("otel.tracer_provider_conflict",
			slog.String("existing_type", fmt.Sprintf("%T", existing)),
			slog.String("action", "overwriting with provide-telemetry tracer provider"),
		)
	}
}

func _warnIfMeterProviderConflict() {
	if _otelMeterProvider != nil {
		return
	}
	existing := otel.GetMeterProvider()
	existingType := fmt.Sprintf("%T", existing)
	if strings.Contains(existingType, "global") || strings.Contains(existingType, "noop") {
		return
	}
	// No type-based suppression. This function is only reached when our own
	// provider field is nil — we have not installed anything — so a live
	// concrete provider on the global belongs to the host by definition, and a
	// host running the same SDK we do is the most likely real conflict, not the
	// least. Ownership is the evidence, not the type.
	if logger := telemetry.Logger(); logger != nil {
		logger.Warn("otel.meter_provider_conflict",
			slog.String("existing_type", fmt.Sprintf("%T", existing)),
			slog.String("action", "overwriting with provide-telemetry meter provider"),
		)
	}
}

func _warnIfLoggerProviderConflict() {
	if _otelLoggerProvider != nil {
		return
	}
	existing := logglobal.GetLoggerProvider()
	existingType := fmt.Sprintf("%T", existing)
	if strings.Contains(existingType, "global") || strings.Contains(existingType, "noop") {
		return
	}
	// No type-based suppression. This function is only reached when our own
	// provider field is nil — we have not installed anything — so a live
	// concrete provider on the global belongs to the host by definition, and a
	// host running the same SDK we do is the most likely real conflict, not the
	// least. Ownership is the evidence, not the type.
	if logger := telemetry.Logger(); logger != nil {
		logger.Warn("otel.logger_provider_conflict",
			slog.String("existing_type", fmt.Sprintf("%T", existing)),
			slog.String("action", "overwriting with provide-telemetry logger provider"),
		)
	}
}

func _setupTracerProvider(state telemetry.BackendSetupState, cfg *telemetry.TelemetryConfig) {
	_providersMu.Lock()
	defer _providersMu.Unlock()

	if !cfg.Tracing.Enabled {
		return
	}
	provider := state.TracerProvider()
	if provider == nil && cfg.Tracing.OTLPEndpoint != "" {
		tp, err := _buildDefaultTracerProvider(cfg)
		if err != nil {
			if logger := telemetry.Logger(); logger != nil {
				logger.Warn("otel.tracer_provider_init_failed", slog.String("error", err.Error()))
			}
		} else {
			provider = tp
		}
	}
	if tp, ok := provider.(*sdktrace.TracerProvider); ok {
		_warnIfTracerProviderConflict()
		_otelTracerProvider = tp
		otel.SetTracerProvider(tp)
		_weSetTracerGlobal = true
	}
}

func _setupMeterProvider(state telemetry.BackendSetupState, cfg *telemetry.TelemetryConfig) {
	_providersMu.Lock()
	defer _providersMu.Unlock()

	if !cfg.Metrics.Enabled {
		_setPromState(_promMetricsDisabled, nil)
		return
	}
	provider := state.MeterProvider()
	hostOwned := provider != nil
	var registry _promRegistryLike
	buildFailed := false
	if !hostOwned && _wantsDefaultMeterProvider(cfg) {
		mp, reg, err := _buildDefaultMeterProvider(cfg)
		if err != nil {
			buildFailed = true
			if logger := telemetry.Logger(); logger != nil {
				logger.Warn("otel.meter_provider_init_failed", slog.String("error", err.Error()))
			}
		} else {
			provider = mp
			registry = reg
		}
	}
	_setPromState(_promStatusAfterSetup(hostOwned, buildFailed, registry), registry)
	if mp, ok := provider.(*sdkmetric.MeterProvider); ok {
		_warnIfMeterProviderConflict()
		_otelMeterProvider = mp
		otel.SetMeterProvider(mp)
		_weSetMeterGlobal = true
	}
}

// _promStatusAfterSetup decides what the Prometheus endpoint reports once
// metrics setup has run with metrics enabled. A build that succeeded without a
// registry is one that never asked for the Prometheus reader.
func _promStatusAfterSetup(hostOwned, buildFailed bool, registry _promRegistryLike) _promStatus {
	if hostOwned {
		return _promHostProvider
	}
	if buildFailed {
		return _promSetupFailed
	}
	if registry == nil {
		return _promNotSelected
	}
	return _promReady
}

func _setupLoggerProvider(state telemetry.BackendSetupState, cfg *telemetry.TelemetryConfig) {
	_providersMu.Lock()
	defer _providersMu.Unlock()

	provider := state.LoggerProvider()
	// cfg.Logging.OTLPEnabled gates default-provider construction independent
	// of the trace/metrics enable flags. When false, we still honour a caller-
	// supplied LoggerProvider injected via WithLoggerProvider — that's an
	// explicit override and shouldn't be silently ignored.
	if provider == nil && cfg.Logging.OTLPEnabled && cfg.Logging.OTLPEndpoint != "" {
		lp, err := _buildLoggerProvider(cfg)
		if err != nil {
			if logger := telemetry.Logger(); logger != nil {
				logger.Warn("otel.logger_provider_init_failed", slog.String("error", err.Error()))
			}
		} else {
			provider = lp
		}
	}
	if lp, ok := provider.(*sdklog.LoggerProvider); ok {
		_warnIfLoggerProviderConflict()
		_otelLoggerProvider = lp
		logglobal.SetLoggerProvider(lp)
		_weSetLoggerGlobal = true
	}
}
