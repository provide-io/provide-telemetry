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

	telemetry "github.com/provide-io/provide-telemetry/go"
	_ "github.com/provide-io/provide-telemetry/go/otel"
)

func requireEnv(name string) string {
	v := os.Getenv(name)
	if v == "" {
		fmt.Fprintf(os.Stderr, "missing required env var: %s\n", name)
		os.Exit(1)
	}
	return v
}

func requireAnyEnv(names ...string) string {
	for _, name := range names {
		if v := os.Getenv(name); v != "" {
			return v
		}
	}
	fmt.Fprintf(os.Stderr, "missing required env var: one of %v\n", names)
	os.Exit(1)
	return ""
}

func main() {
	backendURL := requireEnv("E2E_BACKEND_URL")
	user := requireEnv("OPENOBSERVE_USER")
	password := requireEnv("OPENOBSERVE_PASSWORD")
	_ = requireAnyEnv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT")

	auth := base64.StdEncoding.EncodeToString([]byte(user + ":" + password))
	if os.Getenv("OTEL_EXPORTER_OTLP_HEADERS") == "" && os.Getenv("OTEL_EXPORTER_OTLP_TRACES_HEADERS") == "" {
		_ = os.Setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=Basic%20"+url.PathEscape(auth))
	}

	if _, err := telemetry.SetupTelemetry(); err != nil {
		fmt.Fprintf(os.Stderr, "setup telemetry: %v\n", err)
		os.Exit(1)
	}

	var traceID string
	err := telemetry.Trace(context.Background(), "go.e2e.cross_language_request", func(spanCtx context.Context) error {
		var spanID string
		traceID, spanID = telemetry.GetTraceContext(spanCtx)
		if traceID == "" || spanID == "" {
			return fmt.Errorf("missing trace context")
		}
		traceparent := fmt.Sprintf("00-%s-%s-01", traceID, spanID)

		req, err := http.NewRequestWithContext(spanCtx, http.MethodGet, backendURL+"/traced", nil)
		if err != nil {
			return fmt.Errorf("create request: %w", err)
		}
		req.Header.Set("traceparent", traceparent)

		client := &http.Client{Timeout: 10 * time.Second}
		resp, err := client.Do(req)
		if err != nil {
			return fmt.Errorf("request failed: %w", err)
		}
		defer resp.Body.Close()
		_, _ = io.ReadAll(resp.Body)

		if resp.StatusCode != http.StatusOK {
			return fmt.Errorf("backend returned HTTP %d", resp.StatusCode)
		}
		return nil
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "%v\n", err)
		os.Exit(1)
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := telemetry.ShutdownTelemetry(shutdownCtx); err != nil {
		fmt.Fprintf(os.Stderr, "shutdown: %v\n", err)
	}

	fmt.Printf("TRACE_ID=%s\n", traceID)
}
