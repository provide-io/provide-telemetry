// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"log/slog"
	"os"
	"testing"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

func TestOTLPCollectorSmoke(t *testing.T) {
	endpoint := os.Getenv("PROVIDE_TEST_OTLP_ENDPOINT")
	if endpoint == "" {
		t.Skip("PROVIDE_TEST_OTLP_ENDPOINT is required")
	}

	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_TELEMETRY_SERVICE_NAME", "provide-telemetry-go-integration")
	t.Setenv("PROVIDE_TRACE_ENABLED", "true")
	t.Setenv("PROVIDE_METRICS_ENABLED", "true")
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint)

	if _, err := telemetry.SetupTelemetry(); err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	ctx := context.Background()
	logger := telemetry.GetLogger(ctx, "integration.collector")
	requests := telemetry.NewCounter("integration.collector.requests")
	if err := telemetry.Trace(ctx, "integration.collector.span", func(spanCtx context.Context) error {
		logger.Info("integration.collector.log", slog.String("suite", "integration"))
		requests.Add(spanCtx, 1, slog.String("suite", "integration"))
		return nil
	}); err != nil {
		t.Fatalf("Trace failed: %v", err)
	}

	if err := telemetry.ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("ShutdownTelemetry failed: %v", err)
	}
}
