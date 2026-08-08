// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// Command flush_collector_probe proves FlushTelemetry puts records on the wire
// without tearing providers down.
//
// Why a standalone process rather than a case in the OTLP smoke test: the
// collector is verified by grepping its debug log after the run, which cannot
// tell *when* a record arrived. If this process also called ShutdownTelemetry,
// shutdown's own drain would be an equally good explanation for anything that
// showed up, and the check would pass with flush completely broken.
//
// So this exits without shutting down. Every signal named below can only have
// reached the collector because flush sent it.
//
// It also emits a second batch after the flush and asserts the providers are
// still installed, which is the other half of the contract — flush drains, it
// does not tear down.
package main

import (
	"context"
	"fmt"
	"log/slog"
	"os"

	telemetry "github.com/provide-io/provide-telemetry/go"
	_ "github.com/provide-io/provide-telemetry/go/otel"
)

func fail(format string, args ...any) {
	fmt.Fprintf(os.Stderr, "flush-collector-probe: FAIL — "+format+"\n", args...)
	os.Exit(1)
}

func allInstalled(s telemetry.SignalStatus) bool {
	return s.Logs && s.Traces && s.Metrics
}

func main() {
	endpoint := os.Getenv("PROVIDE_TEST_OTLP_ENDPOINT")
	if endpoint == "" {
		fmt.Fprintln(os.Stderr, "flush-collector-probe: PROVIDE_TEST_OTLP_ENDPOINT unset; skipping")
		return
	}

	_ = os.Setenv("PROVIDE_TELEMETRY_SERVICE_NAME", "provide-telemetry-go-integration")
	_ = os.Setenv("PROVIDE_TRACE_ENABLED", "true")
	_ = os.Setenv("PROVIDE_METRICS_ENABLED", "true")
	_ = os.Setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", endpoint+"/v1/traces")
	_ = os.Setenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", endpoint+"/v1/metrics")
	_ = os.Setenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", endpoint+"/v1/logs")

	if _, err := telemetry.SetupTelemetry(); err != nil {
		fail("setup failed: %v", err)
	}

	if before := telemetry.GetRuntimeStatus(); !allInstalled(before.Providers) {
		fail("providers not installed before flush: %+v", before.Providers)
	}

	requests := telemetry.NewCounter("integration.flush.requests", telemetry.WithUnit("1"))

	ctx := context.Background()
	// Batch one — only a working flush can deliver this, since we never shut down.
	if err := telemetry.Trace(ctx, "integration.flush.span", func(spanCtx context.Context) error {
		telemetry.Logger().InfoContext(spanCtx, "integration.flush.log", "suite", "flush")
		requests.Add(spanCtx, 1, slog.String("suite", "flush"))
		return nil
	}); err != nil {
		fail("traced work returned %v", err)
	}

	if err := telemetry.FlushTelemetry(ctx); err != nil {
		fail("FlushTelemetry returned %v against a reachable collector", err)
	}

	// Flush drains; it must not tear down.
	after := telemetry.GetRuntimeStatus()
	if !allInstalled(after.Providers) {
		fail("flush tore providers down: %+v", after.Providers)
	}
	if !after.SetupDone {
		fail("flush cleared setup state")
	}

	if err := telemetry.Trace(ctx, "integration.flush.after.span", func(spanCtx context.Context) error {
		telemetry.Logger().InfoContext(spanCtx, "integration.flush.after.log", "suite", "flush-after")
		requests.Add(spanCtx, 1, slog.String("suite", "flush-after"))
		return nil
	}); err != nil {
		fail("post-flush traced work returned %v", err)
	}

	if err := telemetry.FlushTelemetry(ctx); err != nil {
		fail("a second FlushTelemetry returned %v; flush is not repeatable", err)
	}

	fmt.Fprintln(os.Stderr, "flush-collector-probe: OK — flushed twice, providers still installed")
	// Deliberately no ShutdownTelemetry: see the package comment.
}
