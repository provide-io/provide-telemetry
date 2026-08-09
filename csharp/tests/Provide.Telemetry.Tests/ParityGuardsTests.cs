// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Diagnostics;
using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// The cross-language guard semantics shared with Python/TypeScript/Go/Rust:
/// the exporter-retries ceiling, the not-set-up guard on runtime updates, the
/// liveness-gated provider-immutability check, and flush-result fidelity.
/// </summary>
[Collection("Telemetry")]
public class ParityGuardsTests
{
    public ParityGuardsTests() => Testing.ResetForTests();

    private static void WithEnv(string key, string value, Action body)
    {
        Environment.SetEnvironmentVariable(key, value);
        try { body(); }
        finally { Environment.SetEnvironmentVariable(key, null); }
    }

    [Theory]
    [InlineData("PROVIDE_EXPORTER_LOGS_RETRIES")]
    [InlineData("PROVIDE_EXPORTER_TRACES_RETRIES")]
    [InlineData("PROVIDE_EXPORTER_METRICS_RETRIES")]
    public void EnvRetries_AboveCeiling_Rejected(string envVar)
    {
        WithEnv(envVar, "101", () =>
        {
            var ex = Assert.Throws<ConfigurationError>(() => ConfigEnv.ConfigFromEnv());
            Assert.Equal($"{envVar} must be at most 100, got 101", ex.Message);
        });
    }

    [Fact]
    public void EnvRetries_AtCeiling_Accepted()
    {
        WithEnv("PROVIDE_EXPORTER_LOGS_RETRIES", "100", () =>
        {
            var cfg = ConfigEnv.ConfigFromEnv();
            Assert.Equal(100, cfg.Exporter.LogsRetries);
        });
    }

    private static void SetRetries(TelemetryConfig cfg, string signal, int retries)
    {
        if (signal == "Logs") cfg.Exporter.LogsRetries = retries;
        else if (signal == "Traces") cfg.Exporter.TracesRetries = retries;
        else cfg.Exporter.MetricsRetries = retries;
    }

    [Theory]
    // One signal at a time: with two of the three over the ceiling, a deleted
    // check for the third still throws on its neighbour's behalf and the gap is
    // invisible. The field name in the message is what tells an operator which
    // of the three they set wrong, so it is asserted, not just the type.
    [InlineData("Logs")]
    [InlineData("Traces")]
    [InlineData("Metrics")]
    public void ExplicitConfigRetries_AboveCeiling_RejectedAtSetup(string signal)
    {
        var cfg = TelemetryConfig.Default();
        SetRetries(cfg, signal, 101);
        var ex = Assert.Throws<ConfigurationError>(() => ProvideTelemetry.SetupTelemetry(cfg));
        Assert.Equal($"Exporter.{signal}Retries must be at most 100, got 101", ex.Message);
        Assert.False(ProvideTelemetry.GetRuntimeStatus().SetupDone);
    }

    [Fact]
    public void ExplicitConfigRetries_AtCeiling_AcceptedAtSetup()
    {
        var cfg = TelemetryConfig.Default();
        cfg.Exporter.LogsRetries = 100;
        var installed = ProvideTelemetry.SetupTelemetry(cfg);
        Assert.Equal(100, installed.Exporter.LogsRetries);
    }

    [Theory]
    [InlineData("Logs")]
    [InlineData("Traces")]
    [InlineData("Metrics")]
    public void ExplicitConfigRetries_AboveCeiling_RejectedAtReconfigure(string signal)
    {
        ProvideTelemetry.SetupTelemetry();
        var cfg = ProvideTelemetry.GetRuntimeConfig()!;
        SetRetries(cfg, signal, 101);
        var ex = Assert.Throws<ConfigurationError>(() => ProvideTelemetry.ReconfigureTelemetry(cfg));
        Assert.Equal($"Exporter.{signal}Retries must be at most 100, got 101", ex.Message);
    }

    [Fact]
    public void UpdateRuntimeConfig_BeforeSetup_Throws()
    {
        var ex = Assert.Throws<TelemetryError>(
            () => ProvideTelemetry.UpdateRuntimeConfig(new RuntimeOverrides { LogLevel = "DEBUG" }));
        Assert.Equal("telemetry not set up: call SetupTelemetry first", ex.Message);
        Assert.False(ProvideTelemetry.GetRuntimeStatus().SetupDone);
    }

    [Fact]
    public void UpdateRuntimeConfig_AfterShutdown_Throws()
    {
        ProvideTelemetry.SetupTelemetry();
        ProvideTelemetry.ShutdownTelemetry();
        Assert.Throws<TelemetryError>(
            () => ProvideTelemetry.UpdateRuntimeConfig(new RuntimeOverrides { LogLevel = "DEBUG" }));
        // The guard must not resurrect setup state.
        Assert.False(ProvideTelemetry.GetRuntimeStatus().SetupDone);
    }

    [Fact]
    public void UpdateRuntimeConfig_AfterSetup_StillApplies()
    {
        ProvideTelemetry.SetupTelemetry();
        ProvideTelemetry.UpdateRuntimeConfig(new RuntimeOverrides { LogLevel = "DEBUG" });
        Assert.Equal("DEBUG", ProvideTelemetry.GetRuntimeConfig()!.Logging.Level);
    }

    [Fact]
    public void ReloadRuntimeFromEnv_BeforeSetup_Throws()
    {
        var ex = Assert.Throws<TelemetryError>(() => ProvideTelemetry.ReloadRuntimeFromEnv());
        Assert.Equal("telemetry not set up: call SetupTelemetry first", ex.Message);
    }

    [Fact]
    public void Reconfigure_BeforeSetup_Throws()
    {
        var ex = Assert.Throws<ConfigurationError>(() => ProvideTelemetry.ReconfigureTelemetry());
        Assert.Equal("telemetry not set up: call SetupTelemetry first", ex.Message);
        // No generation may be published by the refusal: a caller who never set
        // up must not end up with status claiming it did.
        Assert.False(ProvideTelemetry.GetRuntimeStatus().SetupDone);
    }

    [Fact]
    public void Reconfigure_AfterShutdown_Throws()
    {
        ProvideTelemetry.SetupTelemetry();
        ProvideTelemetry.ShutdownTelemetry();
        var cfg = TelemetryConfig.Default();
        Assert.Throws<ConfigurationError>(() => ProvideTelemetry.ReconfigureTelemetry(cfg));
        Assert.False(ProvideTelemetry.GetRuntimeStatus().SetupDone);
    }

    [Fact]
    public void Reconfigure_FallbackMode_AppliesProviderFields()
    {
        // No OTLP endpoints — no owned providers — so provider-field diffs must
        // be applied, not rejected: nothing has baked anything in.
        ProvideTelemetry.SetupTelemetry();
        var target = ProvideTelemetry.GetRuntimeConfig()!;
        target.ServiceName = "renamed-in-fallback";
        var applied = ProvideTelemetry.ReconfigureTelemetry(target);
        Assert.Equal("renamed-in-fallback", applied.ServiceName);
        Assert.Equal("renamed-in-fallback", ProvideTelemetry.GetRuntimeConfig()!.ServiceName);
    }

    private static TelemetryConfig ConfigWithLiveLogsProvider()
    {
        var cfg = TelemetryConfig.Default();
        // Connection-refused endpoint: the exporter installs without connecting.
        cfg.Logging.OtlpEndpoint = "http://127.0.0.1:9";
        cfg.Logging.OtlpEnabled = true;
        return cfg;
    }

    [Fact]
    public void Reconfigure_LiveLogsProvider_RejectsBakedEndpoint()
    {
        ProvideTelemetry.SetupTelemetry(ConfigWithLiveLogsProvider());
        Assert.True(ProvideTelemetry.GetRuntimeStatus().Providers.Logs);

        var target = ProvideTelemetry.GetRuntimeConfig()!;
        target.Logging.OtlpEndpoint = "http://127.0.0.1:19";
        Assert.Throws<ProviderImmutableError>(() => ProvideTelemetry.ReconfigureTelemetry(target));

        var identity = ProvideTelemetry.GetRuntimeConfig()!;
        identity.ServiceName = "renamed-while-live";
        Assert.Throws<ProviderImmutableError>(() => ProvideTelemetry.ReconfigureTelemetry(identity));
    }

    [Fact]
    public void Reconfigure_LiveLogsProvider_AllowsOtherSignalsEndpoint()
    {
        // Per-signal gating: a live logs provider does not freeze the traces
        // endpoint — no traces provider is installed to have baked it.
        ProvideTelemetry.SetupTelemetry(ConfigWithLiveLogsProvider());
        var target = ProvideTelemetry.GetRuntimeConfig()!;
        target.Tracing.OtlpEndpoint = "http://127.0.0.1:19";
        var applied = ProvideTelemetry.ReconfigureTelemetry(target);
        Assert.Equal("http://127.0.0.1:19", applied.Tracing.OtlpEndpoint);
    }

    [Fact]
    public void Flush_HostAdoptedProvider_ReportsNotOwned()
    {
        TelemetryBackendRegistry.MarkHostProviders(logs: true);
        ProvideTelemetry.SetupTelemetry();
        var result = ProvideTelemetry.FlushTelemetry();
        // The host's provider is installed but not ours to drain.
        Assert.True(result.Logs.NotOwned);
        Assert.False(result.Logs.NotInstalled);
        Assert.False(result.Logs.Flushed);
        // Nothing at all behind traces: genuinely not installed.
        Assert.True(result.Traces.NotInstalled);
        Assert.False(result.Traces.NotOwned);
    }

    [Fact]
    public void Flush_ZeroOrNegativeTimeout_ReturnsPromptly()
    {
        // Zero budget means abandon immediately — never an unbounded drain.
        ProvideTelemetry.SetupTelemetry(ConfigWithLiveLogsProvider());
        ProvideTelemetry.GetLogger("guard").Info("queued.for.flush");
        var sw = Stopwatch.StartNew();
        var zero = ProvideTelemetry.FlushTelemetry(TimeSpan.Zero);
        var negative = ProvideTelemetry.FlushTelemetry(TimeSpan.FromSeconds(-1));
        sw.Stop();
        Assert.NotNull(zero);
        Assert.NotNull(negative);
        Assert.True(sw.Elapsed < TimeSpan.FromSeconds(5),
            $"zero-budget flush must not block; took {sw.Elapsed}");
    }
}
