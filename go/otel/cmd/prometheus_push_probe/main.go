// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// Command prometheus_push_probe records the push_ingestion instruments and
// pushes them to Prometheus over OTLP.
//
// Tier 1 of the Prometheus contract: no Prometheus-specific code, only the
// ordinary OTLP metrics exporter pointed at a Prometheus 3 OTLP receiver. The
// instruments are listed in spec/prometheus_fixtures.yaml (push_ingestion); the
// E2E test in e2e/test_prometheus_push_e2e.py queries them back.
//
// Inputs (environment):
//
//	OTEL_EXPORTER_OTLP_METRICS_ENDPOINT   e.g. http://127.0.0.1:9090/api/v1/otlp/v1/metrics
//	PROVIDE_TELEMETRY_SERVICE_NAME        becomes the Prometheus job label
//	PROVIDE_PROM_PROBE_PREFIX             dotted metric-name prefix for this run
package main

import (
	"context"
	"fmt"
	"log/slog"
	"os"

	telemetry "github.com/provide-io/provide-telemetry/go"
	_ "github.com/provide-io/provide-telemetry/go/otel"
)

func main() {
	prefix := os.Getenv("PROVIDE_PROM_PROBE_PREFIX")
	if prefix == "" || os.Getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT") == "" {
		fmt.Fprintln(os.Stderr, "prometheus-push-probe: endpoint or prefix unset")
		os.Exit(2)
	}
	if os.Getenv("PROVIDE_TRACE_ENABLED") == "" {
		_ = os.Setenv("PROVIDE_TRACE_ENABLED", "false")
	}
	if _, err := telemetry.SetupTelemetry(); err != nil {
		fmt.Fprintf(os.Stderr, "prometheus-push-probe: FAIL — setup: %v\n", err)
		os.Exit(1)
	}

	ctx := context.Background()
	telemetry.NewCounter(prefix+".requests").Add(ctx, 3, slog.String("route", "/a"))
	telemetry.NewHistogram(prefix+".request.duration", telemetry.WithUnit("ms")).Record(ctx, 12, slog.String("route", "/a"))
	telemetry.NewGauge(prefix+".cpu.utilization", telemetry.WithUnit("1")).Set(ctx, 1, slog.String("core", "0"))

	// Shutdown drains the periodic reader, which is what puts the data on the wire.
	if err := telemetry.ShutdownTelemetry(ctx); err != nil {
		fmt.Fprintf(os.Stderr, "prometheus-push-probe: FAIL — shutdown: %v\n", err)
		os.Exit(1)
	}
	fmt.Fprintln(os.Stderr, "prometheus-push-probe: OK")
}
