// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// Cross-language distributed tracing E2E client (Go).
//
// Reads from env:
//
//	E2E_BACKEND_URL              — base URL of the Python backend
//	OPENOBSERVE_USER             — OpenObserve basic-auth username
//	OPENOBSERVE_PASSWORD         — OpenObserve basic-auth password
//	OTEL_EXPORTER_OTLP_ENDPOINT  — OTLP base endpoint
//
// Prints to stdout:
//
//	TRACE_ID={traceId}
//
// Exit code 0 on success, 1 on any error.
package main

import (
	"context"
	"encoding/base64"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

func requireEnv(name string) string {
	v := os.Getenv(name)
	if v == "" {
		fmt.Fprintf(os.Stderr, "missing required env var: %s\n", name)
		os.Exit(1)
	}
	return v
}

func main() {
	backendURL := requireEnv("E2E_BACKEND_URL")
	user := requireEnv("OPENOBSERVE_USER")
	password := requireEnv("OPENOBSERVE_PASSWORD")
	endpoint := requireEnv("OTEL_EXPORTER_OTLP_ENDPOINT")

	auth := base64.StdEncoding.EncodeToString([]byte(user + ":" + password))

	// Set up a real OTel tracer provider exporting to OpenObserve.
	ctx := context.Background()
	traceEndpoint := endpoint + "/v1/traces"

	parsed, err := url.Parse(traceEndpoint)
	if err != nil {
		fmt.Fprintf(os.Stderr, "parse endpoint: %v\n", err)
		os.Exit(1)
	}

	opts := []otlptracehttp.Option{
		otlptracehttp.WithEndpointURL(traceEndpoint),
		otlptracehttp.WithHeaders(map[string]string{
			"Authorization": "Basic " + auth,
		}),
	}
	if parsed.Scheme == "http" {
		opts = append(opts, otlptracehttp.WithInsecure())
	}

	exporter, err := otlptracehttp.New(ctx, opts...)
	if err != nil {
		fmt.Fprintf(os.Stderr, "create exporter: %v\n", err)
		os.Exit(1)
	}

	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter,
			sdktrace.WithBatchTimeout(200*time.Millisecond),
			sdktrace.WithMaxExportBatchSize(1),
		),
	)
	otel.SetTracerProvider(tp)

	tracer := tp.Tracer("go.e2e.client")

	// Create a root span and propagate traceparent to the Python backend.
	spanCtx, span := tracer.Start(ctx, "go.e2e.cross_language_request")

	sc := span.SpanContext()
	traceID := sc.TraceID().String()
	spanID := sc.SpanID().String()
	traceparent := fmt.Sprintf("00-%s-%s-01", traceID, spanID)

	// Call the Python backend with the traceparent header.
	req, err := http.NewRequestWithContext(spanCtx, http.MethodGet, backendURL+"/traced", nil)
	if err != nil {
		fmt.Fprintf(os.Stderr, "create request: %v\n", err)
		os.Exit(1)
	}
	req.Header.Set("traceparent", traceparent)

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		fmt.Fprintf(os.Stderr, "request failed: %v\n", err)
		os.Exit(1)
	}
	defer resp.Body.Close()
	_, _ = io.ReadAll(resp.Body)

	if resp.StatusCode != http.StatusOK {
		fmt.Fprintf(os.Stderr, "backend returned HTTP %d\n", resp.StatusCode)
		os.Exit(1)
	}

	span.End()

	// Flush and shutdown.
	if err := tp.ForceFlush(ctx); err != nil {
		fmt.Fprintf(os.Stderr, "force flush: %v\n", err)
	}
	if err := tp.Shutdown(ctx); err != nil {
		fmt.Fprintf(os.Stderr, "shutdown: %v\n", err)
	}

	fmt.Printf("TRACE_ID=%s\n", traceID)
}
