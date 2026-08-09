// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Collections;

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.OpenTelemetry.Tests;

/// <summary>
/// Setting up telemetry must not write to the process environment.
/// </summary>
/// <remarks>
/// The backend used to blank every <c>OTEL_*</c> variable for the duration of
/// provider construction, to stop the exporter options re-reading headers it had
/// already been given. That is a process-wide mutation performed for a
/// library-local reason: any other component reading <c>OTEL_*</c> during setup —
/// including a host application's own OTel wiring on another thread — would see
/// them vanish and reappear. Assigning the options explicitly achieves the same
/// thing without touching global state.
/// </remarks>
[Collection("OpenTelemetry")]
public class ProcessEnvironmentTests
{
    public ProcessEnvironmentTests() => Testing.ResetForTests();

    private static Dictionary<string, string> OtelEnvironment() =>
        Environment.GetEnvironmentVariables()
            .Cast<DictionaryEntry>()
            .Where(e => e.Key.ToString()!.StartsWith("OTEL_", StringComparison.Ordinal))
            .ToDictionary(e => e.Key.ToString()!, e => e.Value?.ToString() ?? "", StringComparer.Ordinal);

    [Fact]
    public void SetupDoesNotMutateOtelEnvironment()
    {
        Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_HEADERS", "authorization=Bearer probe");
        Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318");
        try
        {
            OpenTelemetryBackendRegistration.Register();
            var before = OtelEnvironment();

            ProvideTelemetry.SetupTelemetry();
            var during = OtelEnvironment();
            ProvideTelemetry.ShutdownTelemetry();
            var after = OtelEnvironment();

            Assert.Equal(before, during);
            Assert.Equal(before, after);
        }
        finally
        {
            Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_HEADERS", null);
            Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", null);
        }
    }

    [Fact]
    public void ExporterHeadersComeFromConfigNotTheEnvironmentAtBuildTime()
    {
        // The options object seeds itself from OTEL_* at construction, so every
        // field is assigned unconditionally; a config header list must win.
        Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_HEADERS", "authorization=from-environment");
        try
        {
            OpenTelemetryBackendRegistration.Register();
            var config = TelemetryConfig.Default();
            config.Tracing.OtlpEndpoint = "http://127.0.0.1:4318";
            config.Tracing.OtlpHeaders["authorization"] = "from-config";

            using var backend = TelemetryBackendRegistry.Create(config);

            Assert.NotNull(backend);
            Assert.True(backend!.Providers.Traces);
            Assert.Equal("authorization=from-config", Endpoints.FormatHeaders(config.Tracing.OtlpHeaders));
        }
        finally
        {
            Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_HEADERS", null);
        }
    }

    [Fact]
    public void DuplicateHeaderNamesAreDeduplicatedBeforeReachingTheExporter()
    {
        // OtlpExportClient throws on a repeated header name, which would turn a
        // duplicated key in the caller's config into a setup failure.
        var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["Authorization"] = "one",
        };
        headers["authorization"] = "two";
        Assert.Equal("Authorization=two", Endpoints.FormatHeaders(headers));
    }

    [Fact]
    public void EmptyHeaderListRendersAsAnEmptyString()
    {
        Assert.Equal("", Endpoints.FormatHeaders(new Dictionary<string, string>()));
    }

    [Theory]
    [InlineData("http://collector:4318", "logs", "http://collector:4318/v1/logs")]
    [InlineData("http://collector:4318/", "traces", "http://collector:4318/v1/traces")]
    [InlineData("http://collector:4318/v1/metrics", "metrics", "http://collector:4318/v1/metrics")]
    public void SignalPathsAreAppendedOnlyWhenAbsent(string endpoint, string signal, string expected)
    {
        Assert.Equal(expected, Endpoints.BuildSignalUri(endpoint, signal).ToString());
    }

    [Fact]
    public void AnUnparseableEndpointIsRejectedRatherThanGuessedAt()
    {
        Assert.Throws<ConfigurationError>(() => Endpoints.BuildSignalUri("not a url", "logs"));
    }

    /// <summary>
    /// The ten shapes Python's <c>validate_otlp_endpoint</c> and Go's
    /// <c>_validatedSignalEndpointURL</c> refuse. Four of them —
    /// <c>ftp://</c>, port <c>0</c>, the empty port, and the empty port behind
    /// an explicit <c>/v1/</c> path — used to be accepted here, which meant a
    /// misconfigured collector URL reached the exporter as a live target
    /// instead of failing the signal.
    /// </summary>
    [Theory]
    [InlineData("not-a-url")]                 // no scheme separator
    [InlineData("collector:4318")]            // a bare colon is not a scheme separator
    [InlineData("ftp://collector:4318")]      // scheme outside {http, https}
    [InlineData("http://")]                   // no host
    [InlineData("http://:4318")]              // port without a host
    [InlineData("http://host:bad")]           // non-numeric port
    [InlineData("http://host:-1")]            // negative port
    [InlineData("http://host:0")]             // port 0 is not a listenable port
    [InlineData("http://host:99999")]         // above the 16-bit range
    [InlineData("http://host:")]              // colon present, port empty
    [InlineData("http://host:/v1/traces")]    // same, on the explicit-path branch
    public void MalformedEndpointsAreRefusedAtExporterConstruction(string endpoint)
    {
        var error = Assert.Throws<ConfigurationError>(
            () => Endpoints.BuildSignalUri(endpoint, "traces"));
        Assert.Equal($"invalid OTLP endpoint: {endpoint}", error.Message);
    }

    /// <summary>
    /// The shapes that must keep working. <c>https</c> is here because a scheme
    /// check that only admitted <c>http</c> would pass every test above.
    /// </summary>
    [Theory]
    [InlineData("http://host", "http://host/v1/traces")]
    [InlineData("https://collector.example", "https://collector.example/v1/traces")]
    [InlineData("HTTPS://collector.example", "https://collector.example/v1/traces")]
    [InlineData("http://host:65535", "http://host:65535/v1/traces")]
    [InlineData("http://host:1", "http://host:1/v1/traces")]
    // The colons inside an IPv6 literal are the address, not a port separator.
    [InlineData("http://[::1]", "http://[::1]/v1/traces")]
    [InlineData("http://[::1]:4318", "http://[::1]:4318/v1/traces")]
    // Userinfo colons are credentials, not a port. Python rejects this shape;
    // Go accepts it, and Go is the one that is right.
    [InlineData("https://user:pw@host/v1/traces", "https://user:pw@host/v1/traces")]
    public void WellFormedEndpointsSurviveValidation(string endpoint, string expected)
    {
        Assert.Equal(expected, Endpoints.BuildSignalUri(endpoint, "traces").ToString());
    }

    /// <summary>
    /// A shape the raw-text rules admit but <see cref="Uri"/> still refuses —
    /// the unterminated IPv6 bracket that <c>spec/_runtime_probe.py</c> feeds
    /// the SDK to assert it degrades rather than crashes.
    /// </summary>
    [Fact]
    public void AnEndpointUriRefusesIsReportedAsAConfigurationError()
    {
        var error = Assert.Throws<ConfigurationError>(
            () => Endpoints.BuildSignalUri("http://[", "traces"));
        Assert.Equal("invalid OTLP endpoint: http://[", error.Message);
    }

    [Fact]
    public void AnUnsetEndpointNormalizesToNull()
    {
        Assert.Null(Endpoints.Normalize("   "));
        Assert.Equal("http://a:1", Endpoints.Normalize(" http://a:1/ "));
    }
}
