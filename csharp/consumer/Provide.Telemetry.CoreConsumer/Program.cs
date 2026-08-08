// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// Proves the core package stands alone: this program references only
// Provide.Telemetry, names no OpenTelemetry type, and still logs, traces,
// records a metric, flushes and shuts down. If the core package ever regains an
// exporter dependency, this still compiles — PackageBoundaryTests is what
// catches that. What this catches is an API that only works once an integration
// has been registered.

using Provide.Telemetry;

ProvideTelemetry.SetupTelemetry(new TelemetryConfig
{
    ServiceName = "core-consumer",
    Environment = "smoke",
    Version = "0.0.0",
});

ProvideTelemetry.GetLogger("core-consumer").Info("consumer.core.start");

using (var span = ProvideTelemetry.GetTracer("core-consumer").StartSpan("consumer.work"))
{
    span.SetAttribute("consumer", "core");
    ProvideTelemetry.Counter("consumer.core.iterations").Add(1);
}

var flush = ProvideTelemetry.FlushTelemetry(TimeSpan.FromSeconds(1));
Console.WriteLine($"logs_not_installed={flush.Logs.NotInstalled}");

ProvideTelemetry.ShutdownTelemetry();
Console.WriteLine("core consumer ok");
