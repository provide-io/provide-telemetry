// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// The object-shaped runtime facade: lifecycle state transitions, the getters,
/// and the two reconfiguration entry points.
/// </summary>
/// <remarks>
/// The state machine is the point of this type — a caller reads
/// <see cref="TelemetryRuntime.State"/> to decide whether telemetry is usable,
/// so a failed reconfigure that left the state reading <c>Ready</c> would be
/// worse than one that threw and said nothing.
/// </remarks>
[Collection("Telemetry")]
public class TelemetryRuntimeTests : IDisposable
{
    public TelemetryRuntimeTests() => Testing.ResetForTests();

    public void Dispose() => Testing.ResetForTests();

    [Fact]
    public void NewRuntime_IsReadyAndOwnedBeforeAnythingStarts()
    {
        var runtime = new TelemetryRuntime();

        Assert.Equal(RuntimeState.Ready, runtime.State);
        Assert.Equal(ProviderMode.Owned, runtime.ProviderMode);
    }

    [Fact]
    public void Start_UsesTheConstructorConfigAndPublishesItToTheProcessRuntime()
    {
        var config = TelemetryConfig.Default();
        config.ServiceName = "facade-svc";
        config.Logging.Level = "WARNING";
        var runtime = new TelemetryRuntime(config);

        var started = runtime.Start();

        Assert.Equal("facade-svc", started.ServiceName);
        Assert.Equal(RuntimeState.Ready, runtime.State);
        Assert.Equal("facade-svc", runtime.GetRuntimeConfig()!.ServiceName);
        Assert.True(runtime.GetRuntimeStatus().SetupDone);
    }

    [Fact]
    public void Constructor_CopiesTheConfigSoLaterMutationCannotChangeWhatStartWillUse()
    {
        var config = TelemetryConfig.Default();
        config.ServiceName = "at-construction";
        var runtime = new TelemetryRuntime(config);

        config.ServiceName = "mutated-after";

        Assert.Equal("at-construction", runtime.Start().ServiceName);
    }

    [Fact]
    public void Start_WithNoConfigFallsBackToTheEnvironment()
    {
        Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", "from-env-facade");
        try
        {
            Assert.Equal("from-env-facade", new TelemetryRuntime().Start().ServiceName);
        }
        finally
        {
            Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", null);
        }
    }

    [Fact]
    public void Shutdown_LeavesTheRuntimeStoppedAndTheProcessRuntimeTornDown()
    {
        var runtime = new TelemetryRuntime();
        runtime.Start();

        runtime.Shutdown();

        Assert.Equal(RuntimeState.Stopped, runtime.State);
        Assert.False(runtime.GetRuntimeStatus().SetupDone);
        Assert.Null(runtime.GetRuntimeConfig());
    }

    [Fact]
    public void Flush_WithNoOwnedProviderReportsEverySignalNotInstalled()
    {
        var runtime = new TelemetryRuntime();
        runtime.Start();

        var result = runtime.Flush(TimeSpan.FromSeconds(1));

        Assert.True(result.Logs.NotInstalled);
        Assert.True(result.Traces.NotInstalled);
        Assert.True(result.Metrics.NotInstalled);
        Assert.False(result.Logs.Flushed);
    }

    [Fact]
    public void Getters_HandBackWorkingInstrumentsBoundToTheRunningGeneration()
    {
        var runtime = new TelemetryRuntime();
        runtime.Start();

        var counter = runtime.GetMeter("facade").CreateCounter("facade.counter");
        counter.Add(4);
        using var span = runtime.GetTracer("facade").StartSpan("work");

        Assert.Equal(4, counter.Value);
        Assert.Equal(32, span.TraceId.Length);
        Assert.Equal(16, span.SpanId.Length);
        // The default-named overloads resolve to the same backing instruments.
        Assert.NotNull(runtime.GetTracer());
        Assert.NotNull(runtime.GetMeter());
        Assert.NotNull(runtime.GetLogger("facade"));
    }

    // ── UpdateConfig ─────────────────────────────────────────────────────────

    [Fact]
    public void UpdateConfig_RejectsANullConfigWithAConfigurationError()
    {
        var runtime = new TelemetryRuntime();
        runtime.Start();

        var error = Assert.Throws<ConfigurationError>(() => runtime.UpdateConfig(null!));
        Assert.Equal("UpdateConfig requires a non-null config", error.Message);
    }

    [Fact]
    public void UpdateConfig_AppliesTheHotFieldsAndReturnsThePublishedConfig()
    {
        var runtime = new TelemetryRuntime();
        runtime.Start();

        var next = TelemetryConfig.Default();
        next.Logging.Level = "ERROR";
        next.Logging.Format = "json";
        next.Logging.Sanitize = false;
        next.Sampling.LogsRate = 0.25;
        next.Sampling.TracesRate = 0.5;
        next.Sampling.MetricsRate = 0.75;
        next.StrictSchema = true;

        var applied = runtime.UpdateConfig(next);

        Assert.Equal("ERROR", applied.Logging.Level);
        Assert.Equal("json", applied.Logging.Format);
        Assert.False(applied.Logging.Sanitize);
        Assert.Equal(0.25, applied.Sampling.LogsRate);
        Assert.True(applied.StrictSchema);
        // The overrides reach the live policy objects, not just the config copy.
        Assert.Equal(0.25, Sampling.GetSamplingPolicy(Signals.Logs).DefaultRate);
        Assert.Equal(0.5, Sampling.GetSamplingPolicy(Signals.Traces).DefaultRate);
        Assert.Equal(0.75, Sampling.GetSamplingPolicy(Signals.Metrics).DefaultRate);
        Assert.True(Schema.GetStrictSchema());
    }

    [Fact]
    public void UpdateConfig_BeforeStartIsRefused()
    {
        var runtime = new TelemetryRuntime();

        var error = Assert.Throws<TelemetryError>(() => runtime.UpdateConfig(TelemetryConfig.Default()));
        Assert.Equal("telemetry not set up: call SetupTelemetry first", error.Message);
    }

    // ── Reconfigure ──────────────────────────────────────────────────────────

    [Fact]
    public void Reconfigure_AppliesTheGivenConfigAndReturnsToReady()
    {
        var runtime = new TelemetryRuntime();
        runtime.Start();

        var next = TelemetryConfig.Default();
        next.ServiceName = "reconfigured";
        var applied = runtime.Reconfigure(next);

        Assert.Equal("reconfigured", applied.ServiceName);
        Assert.Equal(RuntimeState.Ready, runtime.State);
        Assert.Equal("reconfigured", runtime.GetRuntimeConfig()!.ServiceName);
    }

    [Fact]
    public void Reconfigure_WithNoArgumentFallsBackToTheConstructorConfig()
    {
        var config = TelemetryConfig.Default();
        config.ServiceName = "constructor-config";
        var runtime = new TelemetryRuntime(config);
        runtime.Start();
        runtime.Reconfigure(TelemetryConfig.Default());
        Assert.Equal("provide-service", runtime.GetRuntimeConfig()!.ServiceName);

        runtime.Reconfigure();

        Assert.Equal("constructor-config", runtime.GetRuntimeConfig()!.ServiceName);
    }

    [Fact]
    public void Reconfigure_FailureLeavesTheRuntimeDegradedAndRethrows()
    {
        // Reconfiguring a runtime that was never started is refused; the state
        // must record that the runtime is not usable rather than staying Ready.
        var runtime = new TelemetryRuntime();

        var error = Assert.Throws<ConfigurationError>(() => runtime.Reconfigure(TelemetryConfig.Default()));

        Assert.Equal("telemetry not set up: call SetupTelemetry first", error.Message);
        Assert.Equal(RuntimeState.Degraded, runtime.State);
    }

    [Fact]
    public void Reconfigure_RecoversToReadyAfterADegradedAttempt()
    {
        var runtime = new TelemetryRuntime();
        Assert.Throws<ConfigurationError>(() => runtime.Reconfigure(TelemetryConfig.Default()));
        Assert.Equal(RuntimeState.Degraded, runtime.State);

        runtime.Start();
        runtime.Reconfigure(TelemetryConfig.Default());

        Assert.Equal(RuntimeState.Ready, runtime.State);
    }
}
