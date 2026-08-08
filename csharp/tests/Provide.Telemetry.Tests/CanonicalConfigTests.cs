// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>Sets an environment variable for the duration of a test.</summary>
internal sealed class TestEnvironment : IDisposable
{
    private readonly List<(string Key, string? Previous)> _previous = new();

    public TestEnvironment(params string[] keysAndValues)
    {
        for (var i = 0; i + 1 < keysAndValues.Length; i += 2)
        {
            var key = keysAndValues[i];
            _previous.Add((key, Environment.GetEnvironmentVariable(key)));
            Environment.SetEnvironmentVariable(key, keysAndValues[i + 1]);
        }
    }

    public void Dispose()
    {
        foreach (var (key, previous) in _previous) Environment.SetEnvironmentVariable(key, previous);
    }
}

[Collection("Telemetry")]
public class CanonicalConfigTests
{
    public CanonicalConfigTests() => Testing.ResetForTests();

    [Fact]
    public void LegacyEnvironmentNamesAreIgnored()
    {
        // PROVIDE_TELEMETRY_ENVIRONMENT was a C#-only alias. Honoring it meant a
        // deployment could set it, see C# pick it up, and see the other four
        // SDKs ignore it — the same environment, four different answers.
        using var env = new TestEnvironment("PROVIDE_TELEMETRY_ENVIRONMENT", "legacy");
        Assert.NotEqual("legacy", ConfigEnv.ConfigFromEnv().Environment);
    }

    [Theory]
    [InlineData("PROVIDE_LOG_OTLP_ENDPOINT")]
    [InlineData("PROVIDE_TRACE_OTLP_ENDPOINT")]
    [InlineData("PROVIDE_METRICS_OTLP_ENDPOINT")]
    [InlineData("PROVIDE_LOG_OTLP_HEADERS")]
    [InlineData("PROVIDE_TRACE_OTLP_HEADERS")]
    [InlineData("PROVIDE_METRICS_OTLP_HEADERS")]
    [InlineData("PROVIDE_BACKPRESSURE_LOGS_MAX_SIZE")]
    [InlineData("PROVIDE_SLO_ENABLE_RED")]
    [InlineData("PROVIDE_SLO_ENABLE_USE")]
    public void NonCanonicalEnvironmentNamesAreIgnored(string key)
    {
        var baseline = ConfigEnv.ConfigFromEnv();
        using var env = new TestEnvironment(key, "http://canary.invalid:4318");
        var observed = ConfigEnv.ConfigFromEnv();

        Assert.Equal(baseline.Logging.OtlpEndpoint, observed.Logging.OtlpEndpoint);
        Assert.Equal(baseline.Tracing.OtlpEndpoint, observed.Tracing.OtlpEndpoint);
        Assert.Equal(baseline.Metrics.OtlpEndpoint, observed.Metrics.OtlpEndpoint);
        Assert.Empty(observed.Tracing.OtlpHeaders);
        Assert.Equal(baseline.Backpressure.LogsMaxSize, observed.Backpressure.LogsMaxSize);
        Assert.Equal(baseline.Slo.EnableRed, observed.Slo.EnableRed);
        Assert.Equal(baseline.Slo.EnableUse, observed.Slo.EnableUse);
    }

    [Fact]
    public void OtlpHeadersPercentDecodeWithoutConvertingPlusToSpace()
    {
        using var env = new TestEnvironment("OTEL_EXPORTER_OTLP_HEADERS", "x=a%2Bb,y=c+d");
        var headers = ConfigEnv.ConfigFromEnv().Logging.OtlpHeaders;
        Assert.Equal("a+b", headers["x"]);
        Assert.Equal("c+d", headers["y"]);
    }

    [Fact]
    public void PerSignalEndpointOverridesSharedEndpoint()
    {
        using var env = new TestEnvironment(
            "OTEL_EXPORTER_OTLP_ENDPOINT", "http://shared.invalid:4318",
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://traces.invalid:4318");
        var cfg = ConfigEnv.ConfigFromEnv();
        Assert.Equal("http://traces.invalid:4318", cfg.Tracing.OtlpEndpoint);
        Assert.Equal("http://shared.invalid:4318", cfg.Logging.OtlpEndpoint);
        Assert.Equal("http://shared.invalid:4318", cfg.Metrics.OtlpEndpoint);
    }

    [Fact]
    public void SchemaDefaultsAreZeroRetriesAndZeroBackoff()
    {
        // spec/telemetry-api.yaml: PROVIDE_EXPORTER_*_RETRIES default 0. The
        // policy object shipped 3 retries and 0.5s backoff, so a C# service that
        // configured nothing retried four times where the others tried once.
        var policy = new ExporterPolicy();
        Assert.Equal(0, policy.Retries);
        Assert.Equal(0.0, policy.BackoffSeconds);

        var cfg = TelemetryConfig.Default();
        Assert.Equal(0, cfg.Exporter.LogsRetries);
        Assert.Equal(0, cfg.Exporter.TracesRetries);
        Assert.Equal(0, cfg.Exporter.MetricsRetries);
    }

    [Theory]
    [InlineData("PROVIDE_SAMPLING_LOGS_RATE", "1.5")]
    [InlineData("PROVIDE_SAMPLING_LOGS_RATE", "-0.1")]
    [InlineData("PROVIDE_TRACE_SAMPLE_RATE", "2")]
    [InlineData("PROVIDE_LOG_PII_MAX_DEPTH", "-1")]
    [InlineData("PROVIDE_EXPORTER_LOGS_RETRIES", "-1")]
    [InlineData("PROVIDE_EXPORTER_LOGS_RETRIES", "101")]
    public void OutOfRangeValuesAreRejectedRatherThanClamped(string key, string value)
    {
        // Clamping would let a typo run in production as a silently different
        // configuration; the operator gets an error naming the variable instead.
        using var env = new TestEnvironment(key, value);
        Assert.Throws<ConfigurationError>(() => ConfigEnv.ConfigFromEnv());
    }

    [Fact]
    public void ExplicitResourceAttributesOverrideEnvironmentAndDetectedValues()
    {
        using var env = new TestEnvironment("OTEL_SERVICE_NAME", "environment-service");
        var config = TelemetryConfig.Default();
        config.ServiceName = "explicit-service";
        config.ResourceAttributes["deployment.environment.name"] = "prod";

        var resource = ResourceBuilder.Build(
            config,
            detected: new Dictionary<string, string> { ["service.name"] = "detected-service" });

        Assert.Equal("explicit-service", resource["service.name"]);
        Assert.Equal("prod", resource["deployment.environment.name"]);
    }

    [Fact]
    public void EnvironmentOutranksDetectedWhenConfigIsAtItsDefault()
    {
        // A service name left at the framework default is not a choice, so it
        // must not outrank an OTEL_SERVICE_NAME the operator did set.
        using var env = new TestEnvironment("OTEL_SERVICE_NAME", "environment-service");
        var resource = ResourceBuilder.Build(
            TelemetryConfig.Default(),
            detected: new Dictionary<string, string> { ["service.name"] = "detected-service" });
        Assert.Equal("environment-service", resource["service.name"]);
    }

    [Fact]
    public void DetectedValuesSurviveWhenNothingElseSetsThem()
    {
        var resource = ResourceBuilder.Build(
            TelemetryConfig.Default(),
            detected: new Dictionary<string, string> { ["host.name"] = "worker-7" });
        Assert.Equal("worker-7", resource["host.name"]);
    }

    [Fact]
    public void ResourceAttributesEnvironmentIsMerged()
    {
        using var env = new TestEnvironment("OTEL_RESOURCE_ATTRIBUTES", "k8s.pod.name=api-0,cloud.region=eu-west-1");
        var resource = ResourceBuilder.Build(TelemetryConfig.Default());
        Assert.Equal("api-0", resource["k8s.pod.name"]);
        Assert.Equal("eu-west-1", resource["cloud.region"]);
    }

    [Fact]
    public void FrameworkDefaultsContributeNoExplicitIdentity()
    {
        // resource_precedence fixture, first case: all defaults, no explicit keys.
        Assert.Empty(ResourceBuilder.Explicit(TelemetryConfig.Default()));
    }
}
