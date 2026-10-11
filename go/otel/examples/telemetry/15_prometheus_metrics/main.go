// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// 15_prometheus_metrics — serve a Prometheus scrape endpoint from the SDK.
//
// Demonstrates:
//   - Enabling the Prometheus pull reader with OTEL_METRICS_EXPORTER=prometheus
//     (use otlp,prometheus to push over OTLP as well)
//   - MetricsHandler from the go/otel module, mounted on a net/http ServeMux
//   - NewCounter and NewHistogram with units, plus NewObservableGauge whose
//     callback runs on every scrape
//   - One in-process scrape, showing the Prometheus names the SDK renders:
//     dots become underscores, counters gain _total, units become suffixes
//   - The SDK's own health as provide_telemetry_* series in the same scrape
//
// Runs offline: the scrape goes through httptest.NewRecorder, so no port is
// bound. For a standalone listener instead, set
// PROVIDE_METRICS_PROMETHEUS_LISTEN=true (binds 127.0.0.1:9464, serves /metrics).
//
// Lives in the go/otel module because MetricsHandler does:
//
//	cd go && go run ./otel/examples/telemetry/15_prometheus_metrics
package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"

	telemetry "github.com/provide-io/provide-telemetry/go"
	provideotel "github.com/provide-io/provide-telemetry/go/otel"
)

// scrape sends one GET /metrics through mux and returns the response.
func scrape(mux http.Handler) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	req.Header.Set("Accept", "text/plain")
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)
	return rec
}

// metricNames returns the family names from the # TYPE lines of a scrape.
func metricNames(body string) []string {
	var names []string
	for _, line := range strings.Split(body, "\n") {
		if fields := strings.Fields(line); len(fields) >= 3 && fields[0] == "#" && fields[1] == "TYPE" {
			names = append(names, fields[2])
		}
	}
	return names
}

func printWithPrefix(names []string, prefix string) {
	for _, n := range names {
		if strings.HasPrefix(n, prefix) {
			fmt.Println("  " + n)
		}
	}
}

func main() {
	fmt.Println("Prometheus Metrics Demo")

	// Enable the pull reader. Prometheus alone keeps the example offline.
	_ = os.Setenv("PROVIDE_TELEMETRY_SERVICE_NAME", "prometheus-example")
	_ = os.Setenv("OTEL_METRICS_EXPORTER", "prometheus")
	if _, err := telemetry.SetupTelemetry(); err != nil {
		slog.Error("setup failed", "err", err)
		os.Exit(1)
	}
	fmt.Println("OTEL_METRICS_EXPORTER=prometheus -> pull reader attached")

	// Mount the handler on the host's own server.
	mux := http.NewServeMux()
	mux.Handle("/metrics", provideotel.MetricsHandler())

	ctx := context.Background()
	fmt.Println("\nRecording instruments:")
	requests := telemetry.NewCounter("example.prom.requests",
		telemetry.WithDescription("Requests handled"), telemetry.WithUnit("1"))
	requests.Add(ctx, 3, slog.String("route", "/checkout"))
	fmt.Println("  counter   example.prom.requests (unit 1)    +3")

	latency := telemetry.NewHistogram("example.prom.latency",
		telemetry.WithDescription("Request latency"), telemetry.WithUnit("ms"))
	for _, v := range []float64{12.5, 40.0, 87.5} {
		latency.Record(ctx, v, slog.String("route", "/checkout"))
	}
	fmt.Println("  histogram example.prom.latency (unit ms)    12.5, 40.0, 87.5")

	queueDepth := 7.0
	depth := telemetry.NewObservableGauge("example.prom.queue_depth",
		func(context.Context) []telemetry.Observation {
			return []telemetry.Observation{{Value: queueDepth, Attrs: []slog.Attr{slog.String("queue", "jobs")}}}
		},
		telemetry.WithDescription("Jobs waiting"), telemetry.WithUnit("1"))
	fmt.Println("  observable gauge example.prom.queue_depth   callback -> 7")

	fmt.Println("\nGET /metrics (in-process via httptest):")
	rec := scrape(mux)
	fmt.Printf("  %d  %s\n", rec.Code, rec.Header().Get("Content-Type"))
	body := rec.Body.String()
	names := metricNames(body)

	fmt.Println("\nYour metrics, as Prometheus names them (ms -> _milliseconds, 1 -> _ratio, counter -> _total):")
	printWithPrefix(names, "example_")
	fmt.Println("\nSDK health series in the same scrape:")
	printWithPrefix(names, "provide_telemetry_")
	for _, line := range strings.Split(body, "\n") {
		if strings.HasPrefix(line, "example_prom_queue_depth") {
			fmt.Println("\nObservable gauge sample: " + line)
		}
	}

	depth.Unregister()
	if err := telemetry.ShutdownTelemetry(ctx); err != nil {
		slog.Error("shutdown failed", "err", err)
	}
	after := scrape(mux)
	fmt.Printf("\nAfter shutdown the handler answers %d: %s\n", after.Code, strings.TrimSpace(after.Body.String()))
	fmt.Println("\nDone!")
}
