// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// The same facade calls as the core consumer, with one extra line: registering
// the OTLP backend. Nothing else about the application changes, which is the
// property the split is meant to deliver.

using Provide.Telemetry;
using Provide.Telemetry.OpenTelemetry;

// Before registration the backend must be inactive, so the assertion after
// setup means registration did something rather than the state having been
// true all along.
if (ProvideTelemetry.GetRuntimeStatus().Providers.Traces)
{
    Console.Error.WriteLine("FAIL traces provider active before registration");
    return 1;
}

OpenTelemetryBackendRegistration.Register();

// An OTLP endpoint is what makes the backend install real providers, so the
// activation assertion below needs one. Nothing is ever delivered to it: this
// consumer proves the artifact wires the backend up, and WireDeliveryTests
// already proves what reaches the wire.
var config = TelemetryConfig.Default();
config.ServiceName = "otel-consumer";
config.Environment = "smoke";
config.Version = "0.0.0";
config.Tracing.OtlpEndpoint = "http://127.0.0.1:4318";
config.Metrics.OtlpEndpoint = "http://127.0.0.1:4318";
config.Logging.OtlpEnabled = true;
config.Logging.OtlpEndpoint = "http://127.0.0.1:4318";
ProvideTelemetry.SetupTelemetry(config);

// The claim the capability matrix makes on behalf of these packages: installing
// the integration package and calling Register() activates the backend.
var status = ProvideTelemetry.GetRuntimeStatus();
if (!status.Providers.Traces)
{
    Console.Error.WriteLine("FAIL traces provider inactive after registration and setup");
    return 1;
}

ProvideTelemetry.GetLogger("otel-consumer").Info("consumer.otel.start");

using (var span = ProvideTelemetry.GetTracer("otel-consumer").StartSpan("consumer.work"))
{
    span.SetAttribute("consumer", "otel");
    ProvideTelemetry.Counter("consumer.otel.iterations").Add(1);
}

ProvideTelemetry.FlushTelemetry(TimeSpan.FromSeconds(1));
ProvideTelemetry.ShutdownTelemetry();
Console.WriteLine("otel consumer OK: registration activated the backend");
return 0;
