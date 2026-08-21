// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Text.Json;
using Provide.Telemetry;

// Minimal consumer outside the test assembly.
Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");
Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", "consumer-smoke");
Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_ENV", "smoke");
Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_VERSION", "0.6.0");
Environment.SetEnvironmentVariable("PROVIDE_LOG_INCLUDE_TIMESTAMP", "false");

Testing.ResetForTests();
var rt = new TelemetryRuntime();
var cfg = rt.Start();
if (cfg.ServiceName != "consumer-smoke")
{
    Console.Error.WriteLine($"FAIL service_name={cfg.ServiceName}");
    return 1;
}

var sw = new StringWriter();
var orig = Console.Error;
Console.SetError(sw);
ProvideTelemetry.SetTraceContext("0af7651916cd43dd8448eb211c80319c", "b7ad6b7169203331");
rt.GetLogger("consumer").Info("consumer.smoke.ok");
Console.SetError(orig);

var line = sw.ToString().Split('\n').Select(l => l.Trim()).FirstOrDefault(l => l.StartsWith('{'));
if (line is null)
{
    Console.Error.WriteLine("FAIL no json log line");
    return 1;
}
using var doc = JsonDocument.Parse(line);
var root = doc.RootElement;
if (root.GetProperty("message").GetString() != "consumer.smoke.ok")
{
    Console.Error.WriteLine($"FAIL message={line}");
    return 1;
}
// The canonical envelope field is "service", not "service.name" — Python's
// add_standard_fields emits the same key. This assertion said "service.name"
// and threw KeyNotFoundException on every run; nothing noticed because the
// consumer was never built or run by CI.
if (root.GetProperty("service").GetString() != "consumer-smoke")
{
    Console.Error.WriteLine($"FAIL service={line}");
    return 1;
}

var counter = ProvideTelemetry.Counter("consumer.smoke.counter");
counter.Add(7);
if (counter.Value != 7)
{
    Console.Error.WriteLine($"FAIL counter={counter.Value}");
    return 1;
}

using (var span = ProvideTelemetry.GetTracer("consumer").StartSpan("consumer.smoke.span"))
{
    if (span.TraceId.Length != 32)
    {
        Console.Error.WriteLine($"FAIL span={span.TraceId}");
        return 1;
    }
}

// ── BCL-only boundary ────────────────────────────────────────────────────────
// The two-package split promises that the core package drags in no
// OpenTelemetry dependency. GetReferencedAssemblies reflects what the compiler
// baked into the shipped assembly, so a reference that crept into the packed
// core shows up here even though nothing in this program mentions OTel.
var coreAssembly = typeof(ProvideTelemetry).Assembly;
var otelReferences = coreAssembly
    .GetReferencedAssemblies()
    .Where(a => a.Name is not null && a.Name.StartsWith("OpenTelemetry", StringComparison.Ordinal))
    .Select(a => a.Name!)
    .ToArray();
if (otelReferences.Length > 0)
{
    Console.Error.WriteLine($"FAIL core package references {string.Join(", ", otelReferences)}");
    return 1;
}

// And nothing OpenTelemetry may be loadable at all in a core-only consumer.
var loadedOtel = AppDomain.CurrentDomain
    .GetAssemblies()
    .Where(a => a.GetName().Name?.StartsWith("OpenTelemetry", StringComparison.Ordinal) == true)
    .Select(a => a.GetName().Name!)
    .ToArray();
if (loadedOtel.Length > 0)
{
    Console.Error.WriteLine($"FAIL OpenTelemetry assembly loaded in a core-only consumer: {string.Join(", ", loadedOtel)}");
    return 1;
}

Console.WriteLine("core-only consumer OK: BCL-only boundary intact");

rt.Flush();
rt.Shutdown();
Console.WriteLine("CONSUMER_SMOKE_OK");
Console.WriteLine(line);
return 0;
