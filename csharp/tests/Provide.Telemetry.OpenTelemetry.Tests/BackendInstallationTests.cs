// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.OpenTelemetry.Tests;

/// <summary>
/// What the OTLP backend does when a provider cannot be installed, and how a
/// record's level reaches the logging pipeline.
/// </summary>
/// <remarks>
/// Fail-open is the shipped default and the reason this backend can be added to
/// a running service without risk: a collector URL that turns out to be
/// unbuildable degrades that one signal to the in-process fallback. Turning
/// fail-open off is an explicit choice to make the misconfiguration loud, and
/// both directions are asserted here.
/// </remarks>
[Collection("OpenTelemetry")]
public class BackendInstallationTests : IDisposable
{
    public BackendInstallationTests() => Testing.ResetForTests();

    public void Dispose() => Testing.ResetForTests();

    /// <summary>
    /// An endpoint the exporter cannot build a signal URI from.
    /// </summary>
    /// <remarks>
    /// <c>Endpoints.BuildSignalUri</c> appends <c>/v1/&lt;signal&gt;</c> and
    /// rejects the result when it is not an absolute URI, which is what makes
    /// this a build-time failure rather than a connect-time one — no network is
    /// touched and the test stays hermetic.
    /// </remarks>
    private const string UnbuildableEndpoint = "collector-with-no-scheme";

    private static TelemetryConfig ConfigWithBadEndpoints()
    {
        var config = TelemetryConfig.Default();
        config.Tracing.OtlpEndpoint = UnbuildableEndpoint;
        config.Metrics.OtlpEndpoint = UnbuildableEndpoint;
        config.Logging.OtlpEndpoint = UnbuildableEndpoint;
        return config;
    }

    [Fact]
    public void AnUnbuildableEndpointIsRejectedBeforeAnythingIsInstalled()
    {
        var error = Assert.Throws<ConfigurationError>(
            () => Endpoints.BuildSignalUri(UnbuildableEndpoint, "traces"));

        Assert.Equal($"invalid OTLP endpoint: {UnbuildableEndpoint}", error.Message);
    }

    [Fact]
    public void FailOpenDegradesEveryUnbuildableSignalToTheFallback()
    {
        var config = ConfigWithBadEndpoints();

        using var backend = new OpenTelemetryBackend(config);

        Assert.Equal(ProviderFlags.None, backend.Providers);
        Assert.False(backend.Providers.Any);
        // With no provider the backend hands back nothing, and core falls back.
        Assert.Null(backend.GetTracer("x"));
        Assert.Null(backend.GetMeter("x"));
    }

    [Theory]
    [InlineData("traces")]
    [InlineData("metrics")]
    [InlineData("logs")]
    public void FailOpenOffMakesAnUnbuildableEndpointLoud(string signal)
    {
        var config = TelemetryConfig.Default();
        // Only the signal under test is misconfigured, so the exception can only
        // have come from that signal's install path.
        switch (signal)
        {
            case "traces":
                config.Tracing.OtlpEndpoint = UnbuildableEndpoint;
                config.Exporter.TracesFailOpen = false;
                break;
            case "metrics":
                config.Metrics.OtlpEndpoint = UnbuildableEndpoint;
                config.Exporter.MetricsFailOpen = false;
                break;
            default:
                config.Logging.OtlpEndpoint = UnbuildableEndpoint;
                config.Exporter.LogsFailOpen = false;
                break;
        }

        var error = Assert.Throws<ConfigurationError>(() => new OpenTelemetryBackend(config));
        Assert.Equal($"invalid OTLP endpoint: {UnbuildableEndpoint}", error.Message);
    }

    [Fact]
    public void ARejectedLogsInstallLeavesNoHalfBuiltPipelineBehind()
    {
        // The logs path builds a DI container before it can fail, so fail-open
        // has to dispose it; a leaked ServiceProvider would keep an exporter and
        // its background thread alive for the life of the process.
        var config = TelemetryConfig.Default();
        config.Logging.OtlpEndpoint = UnbuildableEndpoint;

        using var backend = new OpenTelemetryBackend(config);

        Assert.False(backend.Providers.Logs);
        // Emitting through a backend with no logs provider is a no-op, not a
        // fault, and must not count as an export failure.
        backend.EmitLog(Record("INFO"));
        Assert.Equal(0, Health.GetHealthSnapshot().LogsExportFailures);
    }

    [Fact]
    public void ADisabledSignalInstallsNoProviderEvenWithAValidEndpoint()
    {
        var config = TelemetryConfig.Default();
        config.Tracing.OtlpEndpoint = "http://127.0.0.1:4318";
        config.Metrics.OtlpEndpoint = "http://127.0.0.1:4318";
        config.Logging.OtlpEndpoint = "http://127.0.0.1:4318";
        config.Tracing.Enabled = false;
        config.Metrics.Enabled = false;
        config.Logging.OtlpEnabled = false;

        using var backend = new OpenTelemetryBackend(config);

        Assert.Equal(ProviderFlags.None, backend.Providers);
    }

    [Fact]
    public void AConstructorWithNoConfigIsRejected()
    {
        Assert.Throws<ArgumentNullException>(() => new OpenTelemetryBackend(null!));
    }

    [Fact]
    public void EmitLogRejectsANullRecord()
    {
        using var backend = new OpenTelemetryBackend(LiveLogsConfig());

        Assert.Throws<ArgumentNullException>(() => backend.EmitLog(null!));
    }

    [Theory]
    // Every canonical level plus one the vocabulary does not contain, which
    // falls back to Information rather than dropping the record.
    [InlineData("TRACE")]
    [InlineData("DEBUG")]
    [InlineData("INFO")]
    [InlineData("WARN")]
    [InlineData("WARNING")]
    [InlineData("ERROR")]
    [InlineData("CRITICAL")]
    [InlineData("bespoke")]
    [InlineData("info")]
    public void EveryLevelReachesTheLoggingPipelineWithoutFaulting(string level)
    {
        using var backend = new OpenTelemetryBackend(LiveLogsConfig());
        Assert.True(backend.Providers.Logs);

        backend.EmitLog(Record(level));

        // Delivery is best-effort, but the bridge itself must not fault: an
        // unrecognised level maps to Information rather than throwing.
        Assert.Equal(0, Health.GetHealthSnapshot().LogsExportFailures);
    }

    [Fact]
    public void ADisposedBackendStopsHandingOutProviders()
    {
        var backend = new OpenTelemetryBackend(LiveLogsConfig());
        Assert.True(backend.Providers.Logs);

        backend.Dispose();
        // Idempotent: a second dispose from a using block must not re-drain.
        backend.Dispose();

        Assert.Equal(ProviderFlags.None, backend.Providers);
        Assert.Null(backend.GetTracer("x"));
        Assert.Null(backend.GetMeter("x"));
    }

    [Fact]
    public void EmitLogAfterShutdownIsSilentlyIgnored()
    {
        var backend = new OpenTelemetryBackend(LiveLogsConfig());
        backend.Shutdown(DateTimeOffset.UtcNow.AddSeconds(1));

        backend.EmitLog(Record("ERROR"));

        Assert.Equal(0, Health.GetHealthSnapshot().LogsExportFailures);
        backend.Dispose();
    }

    /// <summary>A config whose logs provider installs against a dead port.</summary>
    private static TelemetryConfig LiveLogsConfig()
    {
        var config = TelemetryConfig.Default();
        // Port 9 is the discard service: the exporter installs without ever
        // completing a connection, so the pipeline is live and no collector is
        // needed.
        config.Logging.OtlpEndpoint = "http://127.0.0.1:9";
        config.Logging.OtlpEnabled = true;
        return config;
    }

    private static CanonicalLogRecord Record(string level) => CanonicalLogRecord.Create(
        DateTimeOffset.UtcNow,
        level,
        "backend.emit.ok",
        "bridge",
        TelemetryConfig.Default(),
        traceId: "",
        spanId: "",
        fields: new Dictionary<string, object?> { ["k"] = "v" });
}
