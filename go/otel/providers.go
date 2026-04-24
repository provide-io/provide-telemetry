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
	if _, isSDK := existing.(*sdktrace.TracerProvider); isSDK {
		return
	}
	if telemetry.Logger != nil {
		telemetry.Logger.Warn("otel.tracer_provider_conflict",
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
	if _, isSDK := existing.(*sdkmetric.MeterProvider); isSDK {
		return
	}
	if telemetry.Logger != nil {
		telemetry.Logger.Warn("otel.meter_provider_conflict",
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
	if _, isSDK := existing.(*sdklog.LoggerProvider); isSDK {
		return
	}
	if telemetry.Logger != nil {
		telemetry.Logger.Warn("otel.logger_provider_conflict",
			slog.String("existing_type", fmt.Sprintf("%T", existing)),
			slog.String("action", "overwriting with provide-telemetry logger provider"),
		)
	}
}

func _setupTracerProvider(state telemetry.BackendSetupState, cfg *telemetry.TelemetryConfig) {
	provider := state.TracerProvider()
	if provider == nil && cfg.Tracing.OTLPEndpoint != "" {
		tp, err := _buildDefaultTracerProvider(cfg)
		if err != nil {
			if telemetry.Logger != nil {
				telemetry.Logger.Warn("otel.tracer_provider_init_failed", slog.String("error", err.Error()))
			}
		} else {
			provider = tp
		}
	}
	if tp, ok := provider.(*sdktrace.TracerProvider); ok {
		_warnIfTracerProviderConflict()
		_otelTracerProvider = tp
		otel.SetTracerProvider(tp)
	}
}

func _setupMeterProvider(state telemetry.BackendSetupState, cfg *telemetry.TelemetryConfig) {
	provider := state.MeterProvider()
	if provider == nil && cfg.Metrics.OTLPEndpoint != "" {
		mp, err := _buildDefaultMeterProvider(cfg)
		if err != nil {
			if telemetry.Logger != nil {
				telemetry.Logger.Warn("otel.meter_provider_init_failed", slog.String("error", err.Error()))
			}
		} else {
			provider = mp
		}
	}
	if mp, ok := provider.(*sdkmetric.MeterProvider); ok {
		_warnIfMeterProviderConflict()
		_otelMeterProvider = mp
		otel.SetMeterProvider(mp)
	}
}

func _setupLoggerProvider(state telemetry.BackendSetupState, cfg *telemetry.TelemetryConfig) {
	provider := state.LoggerProvider()
	if provider == nil && cfg.Logging.OTLPEndpoint != "" {
		lp, err := _buildDefaultLoggerProvider(cfg)
		if err != nil {
			if telemetry.Logger != nil {
				telemetry.Logger.Warn("otel.logger_provider_init_failed", slog.String("error", err.Error()))
			}
		} else {
			provider = lp
		}
	}
	if lp, ok := provider.(*sdklog.LoggerProvider); ok {
		_warnIfLoggerProviderConflict()
		_otelLoggerProvider = lp
		logglobal.SetLoggerProvider(lp)
	}
}
