// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// Command prometheus_scrape_probe serves metrics on the Tier 3 listener for a
// real Prometheus to scrape, then waits until stdin closes or it is signalled.
//
// The listener is configured by the ordinary environment variables
// (PROVIDE_METRICS_PROMETHEUS_LISTEN, OTEL_EXPORTER_PROMETHEUS_PORT,
// PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG, ...); e2e/test_prometheus_scrape_e2e.py
// starts it once plain and once secured, and checks what Prometheus stored.
// It records a counter and an observable gauge so both instrument families
// cross the scrape. It prints "ready" once the listener is up.
package main

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/signal"
	"syscall"

	telemetry "github.com/provide-io/provide-telemetry/go"
	_ "github.com/provide-io/provide-telemetry/go/otel"
)

func main() {
	if _, err := telemetry.SetupTelemetry(); err != nil {
		fmt.Fprintf(os.Stderr, "prometheus-scrape-probe: FAIL — setup: %v\n", err)
		os.Exit(1)
	}
	if msg := telemetry.GetHealthSnapshot().SetupError; msg != "" {
		fmt.Fprintf(os.Stderr, "prometheus-scrape-probe: FAIL — %s\n", msg)
		os.Exit(1)
	}
	ctx := context.Background()
	telemetry.NewCounter("e2e.scrape.requests").Add(ctx, 3)
	telemetry.NewObservableGauge("e2e.scrape.temperature", func(context.Context) []telemetry.Observation {
		return []telemetry.Observation{{Value: 41.5}}
	}, telemetry.WithUnit("Cel"))
	fmt.Println("ready")

	done := make(chan struct{})
	go func() {
		_, _ = io.Copy(io.Discard, os.Stdin)
		close(done)
	}()
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, syscall.SIGTERM, os.Interrupt)
	select {
	case <-done:
	case <-signals:
	}
	_ = telemetry.ShutdownTelemetry(ctx)
}
