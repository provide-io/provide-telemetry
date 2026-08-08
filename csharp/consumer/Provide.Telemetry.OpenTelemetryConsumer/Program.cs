// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// The same facade calls as the core consumer, with one extra line: registering
// the OTLP backend. Nothing else about the application changes, which is the
// property the split is meant to deliver.

using Provide.Telemetry;
using Provide.Telemetry.OpenTelemetry;

OpenTelemetryBackendRegistration.Register();

ProvideTelemetry.SetupTelemetry(new TelemetryConfig
{
    ServiceName = "otel-consumer",
    Environment = "smoke",
    Version = "0.0.0",
});

ProvideTelemetry.GetLogger("otel-consumer").Info("consumer.otel.start");

using (var span = ProvideTelemetry.GetTracer("otel-consumer").StartSpan("consumer.work"))
{
    span.SetAttribute("consumer", "otel");
    ProvideTelemetry.Counter("consumer.otel.iterations").Add(1);
}

ProvideTelemetry.FlushTelemetry(TimeSpan.FromSeconds(1));
ProvideTelemetry.ShutdownTelemetry();
Console.WriteLine("otel consumer ok");
