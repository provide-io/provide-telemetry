// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Provide.Telemetry.OpenTelemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// What the lifecycle does when something upstream of it fails: a config that
/// cannot be cloned, an environment that cannot be parsed, and a backend
/// factory that refuses to build.
/// </summary>
/// <remarks>
/// Degradation is the contract here — telemetry is never the reason an
/// application fails to start — so each test asserts both that the process kept
/// going and what it fell back to.
/// </remarks>
[Collection("Telemetry")]
public class SetupFailureModeTests : IDisposable
{
    public SetupFailureModeTests() => Testing.ResetForTests();

    public void Dispose()
    {
        Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", null);
        // The registry is process-wide, so anything that displaced the suite's
        // factory has to hand it back before the next test runs.
        OpenTelemetryBackendRegistration.Register();
        Testing.ResetForTests();
    }

    [Fact]
    public void AConfigThatCannotBeClonedSurfacesAsAConfigurationError()
    {
        // Setup wraps every non-configuration fault from the config path so a
        // caller has one exception type to catch, with the original cause
        // preserved rather than swallowed.
        var config = TelemetryConfig.Default();
        config.Logging = null!;

        var error = Assert.Throws<ConfigurationError>(() => ProvideTelemetry.SetupTelemetry(config));

        Assert.IsType<NullReferenceException>(error.InnerException);
        Assert.False(ProvideTelemetry.GetRuntimeStatus().SetupDone);
    }

    [Fact]
    public void AConfigurationErrorFromTheEnvironmentIsNotDoubleWrapped()
    {
        Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", "ftp://collector/otlp");

        var error = Assert.Throws<ConfigurationError>(() => ProvideTelemetry.SetupTelemetry());

        Assert.Equal("invalid OTLP endpoint: ftp://collector/otlp", error.Message);
        Assert.Null(error.InnerException);
    }

    [Fact]
    public void RuntimeStatusFallsBackToDefaultsWhenTheEnvironmentCannotBeParsed()
    {
        // Status is what a health endpoint calls. Reading it must never throw,
        // even when the very environment that would be reported is malformed.
        Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", "ftp://collector/otlp");

        var status = ProvideTelemetry.GetRuntimeStatus();

        Assert.False(status.SetupDone);
        Assert.True(status.Signals.Traces);
        Assert.True(status.Signals.Metrics);
        Assert.True(status.Fallback.Logs);
        Assert.Equal("", status.SetupError);
    }

    [Fact]
    public void LazyInitFallsBackToTheDefaultConfigWhenTheBackendRefusesToBuild()
    {
        // No explicit SetupTelemetry: the first logger call starts the runtime,
        // and a factory that rejects the config must degrade to the in-process
        // fallbacks rather than fault the caller's log statement.
        TelemetryBackendRegistry.Register(
            _ => throw new ConfigurationError("backend refuses this config"));

        var writer = new StringWriter();
        var original = Console.Error;
        Console.SetError(writer);
        try
        {
            ProvideTelemetry.GetLogger("lazy").Info("lazy.init.ok");
        }
        finally
        {
            Console.SetError(original);
        }

        Assert.Contains("lazy.init.ok", writer.ToString());
        Assert.Null(Setup.CurrentBackend);
        Assert.Equal("provide-service", ProvideTelemetry.GetRuntimeConfig()!.ServiceName);
        Assert.Equal(1, Health.GetHealthSnapshot().LogsEmitted);
    }

    [Fact]
    public void ReconfigureWithNoArgumentRereadsTheEnvironment()
    {
        ProvideTelemetry.SetupTelemetry();
        Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", "reconfigured-from-env");
        try
        {
            var applied = ProvideTelemetry.ReconfigureTelemetry();

            Assert.Equal("reconfigured-from-env", applied.ServiceName);
        }
        finally
        {
            Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", null);
        }
    }

    [Fact]
    public void ShutdownWithNoBackendInstalledIsStillIdempotent()
    {
        ProvideTelemetry.SetupTelemetry();

        ProvideTelemetry.ShutdownTelemetry();
        ProvideTelemetry.ShutdownTelemetry();

        Assert.False(ProvideTelemetry.GetRuntimeStatus().SetupDone);
        Assert.Null(ProvideTelemetry.GetRuntimeConfig());
    }

    [Fact]
    public void ShutdownClearsStrictSchemaSoTheNextStartBeginsLenient()
    {
        var config = TelemetryConfig.Default();
        config.StrictSchema = true;
        ProvideTelemetry.SetupTelemetry(config);
        Assert.True(Schema.GetStrictSchema());

        ProvideTelemetry.ShutdownTelemetry();

        Assert.False(Schema.GetStrictSchema());
    }

    [Fact]
    public void StrictEventNameAloneAlsoTurnsStrictSchemaOn()
    {
        // The two settings are separate knobs on the config but one switch on
        // the validator; either being set has to arm it.
        var config = TelemetryConfig.Default();
        config.EventSchema.StrictEventName = true;

        ProvideTelemetry.SetupTelemetry(config);

        Assert.True(Schema.GetStrictSchema());
    }

    [Fact]
    public void ADisabledSignalReportsNeitherAProviderNorAnEnabledSignal()
    {
        var config = TelemetryConfig.Default();
        config.Tracing.Enabled = false;
        config.Metrics.Enabled = false;
        ProvideTelemetry.SetupTelemetry(config);

        var status = ProvideTelemetry.GetRuntimeStatus();

        Assert.False(status.Signals.Traces);
        Assert.False(status.Signals.Metrics);
        Assert.True(status.Signals.Logs);
        Assert.False(status.Providers.Traces);
        Assert.False(status.Providers.Metrics);
    }

    [Fact]
    public void HostAdoptionIsSuppressedForADisabledSignalSoStatusMatchesTheEmitPath()
    {
        // A host may have installed a tracer provider, but if tracing is off in
        // our config nothing of ours emits through it; reporting the provider
        // would tell an operator spans are flowing when none are.
        TelemetryBackendRegistry.MarkHostProviders(traces: true, metrics: true, logs: true);
        var config = TelemetryConfig.Default();
        config.Tracing.Enabled = false;
        ProvideTelemetry.SetupTelemetry(config);

        var status = ProvideTelemetry.GetRuntimeStatus();

        Assert.False(status.Providers.Traces);
        Assert.True(status.Fallback.Traces);
        Assert.True(status.Providers.Metrics);
        Assert.True(status.Providers.Logs);
    }

    [Fact]
    public void HostAdoptionIsReportedBeforeAnySetupHasHappened()
    {
        TelemetryBackendRegistry.MarkHostProviders(traces: true);

        var status = ProvideTelemetry.GetRuntimeStatus();

        Assert.False(status.SetupDone);
        Assert.True(status.Providers.Traces);
        Assert.False(status.Fallback.Traces);
    }

    [Fact]
    public void TracingAndMetricsGatesFollowTheRunningConfig()
    {
        Assert.True(Setup.IsTracingEnabled());
        Assert.True(Setup.IsMetricsEnabled());

        var config = TelemetryConfig.Default();
        config.Tracing.Enabled = false;
        config.Metrics.Enabled = false;
        ProvideTelemetry.SetupTelemetry(config);

        Assert.False(Setup.IsTracingEnabled());
        Assert.False(Setup.IsMetricsEnabled());
    }
}
