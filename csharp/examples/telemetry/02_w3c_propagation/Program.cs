// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

// 02_w3c_propagation — W3C trace-context propagation via headers.
//
// Demonstrates:
//   - ExtractW3CContext from header map (simulated incoming request)
//   - BindPropagationContext / GetTraceContext lifecycle
//   - Session context binding with BindSessionContext / GetSessionID

using Provide.Telemetry;

Console.WriteLine("W3C Propagation Demo");

Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");
Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", "csharp-example-w3c");

Testing.ResetForTests();
ProvideTelemetry.SetupTelemetry();
var log = ProvideTelemetry.GetLogger("examples.w3c");

Console.WriteLine("HTTP request with W3C traceparent/tracestate/baggage");
var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
{
    ["traceparent"] = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    ["tracestate"] = "vendor=value",
    ["baggage"] = "user_id=123",
};

var pc = ProvideTelemetry.ExtractW3CContext(headers);
Console.WriteLine($"  Extracted trace_id={pc.TraceID}");
Console.WriteLine($"  Extracted span_id={pc.SpanID}");
Console.WriteLine($"  Baggage: {pc.Baggage}");

ProvideTelemetry.BindPropagationContext(pc);
var receivedEvt = ProvideTelemetry.Event("example", "w3c", "received");
log.Info(receivedEvt.Event);

var tc = ProvideTelemetry.GetTraceContext();
Console.WriteLine($"  Bound trace_id={tc.TraceId}");
Console.WriteLine($"  Bound span_id={tc.SpanId}");

Console.WriteLine("\nManual propagation context bind/clear");
var headers2 = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
{
    ["traceparent"] = "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01",
    ["tracestate"] = "game=chess",
};
var pc2 = ProvideTelemetry.ExtractW3CContext(headers2);
ProvideTelemetry.ClearContext();
ProvideTelemetry.BindPropagationContext(pc2);
var tc2 = ProvideTelemetry.GetTraceContext();
Console.WriteLine($"  Bound trace_id={tc2.TraceId}");
Console.WriteLine($"  Bound span_id={tc2.SpanId}");

Console.WriteLine("\nSession context binding");
ProvideTelemetry.BindSessionContext("session-42");
var sessionId = ProvideTelemetry.GetSessionID();
Console.WriteLine($"  session_id={sessionId}");
ProvideTelemetry.ClearSessionContext();
var afterSession = ProvideTelemetry.GetSessionID();
Console.WriteLine($"  After clear: session_id=\"{afterSession}\"");

ProvideTelemetry.FlushTelemetry();
ProvideTelemetry.ShutdownTelemetry();
Console.WriteLine("\nDone!");
Environment.Exit(0);
