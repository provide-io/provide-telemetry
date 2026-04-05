// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// 02_w3c_propagation — W3C trace-context propagation via net/http headers.
//
// Demonstrates:
//   - ExtractW3CContext from http.Header (simulated incoming request)
//   - BindPropagationContext / GetPropagationContext lifecycle
//   - GetTraceContext for downstream correlation
//   - Session context binding with BindSessionContext / GetSessionID
package main

import (
	"context"
	"fmt"
	"net/http"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

func main() {
	fmt.Println("W3C Propagation Demo\n")

	_, err := telemetry.SetupTelemetry()
	if err != nil {
		telemetry.Logger.Error("setup failed", "err", err)
		return
	}
	defer func() { _ = telemetry.ShutdownTelemetry(context.Background()) }()

	ctx := context.Background()
	log := telemetry.GetLogger(ctx, "examples.w3c")

	// HTTP request with full W3C header propagation
	fmt.Println("HTTP request with W3C traceparent/tracestate/baggage")
	headers := http.Header{}
	headers.Set("traceparent", "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
	headers.Set("tracestate", "vendor=value")
	headers.Set("baggage", "user_id=123")

	pc := telemetry.ExtractW3CContext(headers)
	fmt.Printf("  Extracted trace_id=%s\n", pc.TraceID)
	fmt.Printf("  Extracted span_id=%s\n", pc.SpanID)
	fmt.Printf("  Baggage: %s\n", pc.Baggage)

	ctx = telemetry.BindPropagationContext(ctx, pc)
	receivedEvt, _ := telemetry.Event("example", "w3c", "received")
	log.InfoContext(ctx, receivedEvt)

	traceID, spanID := telemetry.GetTraceContext(ctx)
	traceEvt, _ := telemetry.Event("example", "w3c", "trace")
	log.InfoContext(ctx, traceEvt, "trace_id", traceID, "span_id", spanID)
	fmt.Printf("  Bound trace_id=%s\n", traceID)
	fmt.Printf("  Bound span_id=%s\n", spanID)

	// Manual propagation bind/clear lifecycle
	fmt.Println("\nManual propagation context bind/clear")
	headers2 := http.Header{}
	headers2.Set("traceparent", "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01")
	headers2.Set("tracestate", "game=chess")

	pc2 := telemetry.ExtractW3CContext(headers2)
	ctx2 := telemetry.BindPropagationContext(context.Background(), pc2)
	traceID2, spanID2 := telemetry.GetTraceContext(ctx2)
	fmt.Printf("  Bound trace_id=%s\n", traceID2)
	fmt.Printf("  Bound span_id=%s\n", spanID2)

	// Session context binding
	fmt.Println("\nSession context binding")
	ctx3 := telemetry.BindSessionContext(context.Background(), "session-42")
	sessionID, _ := telemetry.GetSessionID(ctx3)
	fmt.Printf("  session_id=%s\n", sessionID)

	ctx3 = telemetry.ClearSessionContext(ctx3)
	afterSession, _ := telemetry.GetSessionID(ctx3)
	fmt.Printf("  After clear: session_id=%q\n", afterSession)

	fmt.Println("\nDone!")
}
