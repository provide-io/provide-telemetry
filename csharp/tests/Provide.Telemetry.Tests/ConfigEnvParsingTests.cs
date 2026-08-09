// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// Environment parsing and the redacted config view.
/// </summary>
/// <remarks>
/// Rejections assert the message as well as the type: the message names the
/// variable and echoes the offending value, which is the only thing that lets
/// an operator fix a bad deployment from a startup crash.
/// </remarks>
[Collection("Telemetry")]
public class ConfigEnvParsingTests : IDisposable
{
    private readonly List<string> _touched = new();

    public ConfigEnvParsingTests() => Testing.ResetForTests();

    public void Dispose()
    {
        foreach (var key in _touched) Environment.SetEnvironmentVariable(key, null);
        Testing.ResetForTests();
    }

    private void Set(string key, string? value)
    {
        _touched.Add(key);
        Environment.SetEnvironmentVariable(key, value);
    }

    // ── required keys ────────────────────────────────────────────────────────

    [Fact]
    public void RequiredKeys_AreSplitTrimmedAndStrippedOfEmptyEntries()
    {
        Set("PROVIDE_TELEMETRY_REQUIRED_KEYS", " user_id , , tenant ,");

        Assert.Equal(new[] { "user_id", "tenant" }, ConfigEnv.ConfigFromEnv().EventSchema.RequiredKeys);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    public void RequiredKeys_BlankValuesLeaveTheListEmpty(string raw)
    {
        Set("PROVIDE_TELEMETRY_REQUIRED_KEYS", raw);

        Assert.Empty(ConfigEnv.ConfigFromEnv().EventSchema.RequiredKeys);
    }

    // ── boolean parsing ──────────────────────────────────────────────────────

    [Theory]
    [InlineData("true", true)]
    [InlineData("False", false)]
    [InlineData("1", true)]
    [InlineData("0", false)]
    [InlineData("yes", true)]
    [InlineData("YES", true)]
    [InlineData("no", false)]
    [InlineData("NO", false)]
    [InlineData("on", true)]
    [InlineData("ON", true)]
    [InlineData("off", false)]
    [InlineData("OFF", false)]
    public void Booleans_AcceptTheDocumentedSpellings(string raw, bool expected)
    {
        Set("PROVIDE_LOG_SANITIZE", raw);

        Assert.Equal(expected, ConfigEnv.ConfigFromEnv().Logging.Sanitize);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    public void Booleans_BlankValuesFallBackToTheDefault(string raw)
    {
        Set("PROVIDE_LOG_SANITIZE", raw);

        Assert.True(ConfigEnv.ConfigFromEnv().Logging.Sanitize);
    }

    [Fact]
    public void Booleans_RejectAnythingElseByName()
    {
        Set("PROVIDE_LOG_SANITIZE", "maybe");

        var error = Assert.Throws<ConfigurationError>(() => ConfigEnv.ConfigFromEnv());
        Assert.Equal("invalid boolean for PROVIDE_LOG_SANITIZE: maybe", error.Message);
    }

    // ── numeric parsing ──────────────────────────────────────────────────────

    [Fact]
    public void Integers_RejectNonNumericValuesByName()
    {
        Set("PROVIDE_LOG_PII_MAX_DEPTH", "deep");

        var error = Assert.Throws<ConfigurationError>(() => ConfigEnv.ConfigFromEnv());
        Assert.Equal("invalid int for PROVIDE_LOG_PII_MAX_DEPTH: deep", error.Message);
    }

    [Fact]
    public void Integers_BlankValuesFallBackToTheDefault()
    {
        Set("PROVIDE_LOG_PII_MAX_DEPTH", "  ");

        Assert.Equal(0, ConfigEnv.ConfigFromEnv().Logging.PiiMaxDepth);
    }

    [Fact]
    public void Floats_RejectNonNumericValuesByName()
    {
        Set("PROVIDE_TRACE_SAMPLE_RATE", "half");

        var error = Assert.Throws<ConfigurationError>(() => ConfigEnv.ConfigFromEnv());
        Assert.Equal("invalid float for PROVIDE_TRACE_SAMPLE_RATE: half", error.Message);
    }

    [Fact]
    public void Floats_ParseWithTheInvariantCultureNotTheHostLocale()
    {
        Set("PROVIDE_TRACE_SAMPLE_RATE", "0.25");

        Assert.Equal(0.25, ConfigEnv.ConfigFromEnv().Tracing.SampleRate);
    }

    // ── endpoint validation ──────────────────────────────────────────────────

    [Theory]
    // Soft validation: something that is not a URI at all is left for the
    // exporter's fail-open path rather than crashing startup.
    [InlineData("not a uri at all")]
    [InlineData("collector 4318")]
    public void Endpoints_UnparseableValuesAreAcceptedAndLeftToTheExporter(string endpoint)
    {
        Set("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint);

        Assert.Equal(endpoint, ConfigEnv.ConfigFromEnv().Tracing.OtlpEndpoint);
    }

    [Theory]
    [InlineData("http://collector:4318")]
    [InlineData("https://collector:4318")]
    [InlineData("grpc://collector:4317")]
    [InlineData("grpcs://collector:4317")]
    public void Endpoints_AcceptEveryTransportSchemeAnOtlpClientCanUse(string endpoint)
    {
        Set("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint);

        Assert.Equal(endpoint, ConfigEnv.ConfigFromEnv().Tracing.OtlpEndpoint);
    }

    [Theory]
    // A scheme no OTLP client could ever attempt is rejected outright. A
    // host:port with no scheme lands here too: Uri parses "localhost" as the
    // scheme, so it is a well-formed URI naming a transport we cannot speak.
    [InlineData("file:///tmp/spans")]
    [InlineData("localhost:4318")]
    public void Endpoints_RejectAnImpossibleSchemeAndEchoIt(string endpoint)
    {
        Set("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint);

        var error = Assert.Throws<ConfigurationError>(() => ConfigEnv.ConfigFromEnv());
        Assert.Equal($"invalid OTLP endpoint: {endpoint}", error.Message);
    }

    [Theory]
    // Each signal is validated by a call of its own, and only a per-signal
    // variable reaches one in isolation: driven through the shared
    // OTEL_EXPORTER_OTLP_ENDPOINT all three see the same bad value, so any two
    // of the checks cover for a missing third and a deleted one is invisible.
    [InlineData("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT")]
    [InlineData("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")]
    [InlineData("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")]
    public void Endpoints_EachSignalIsValidatedOnItsOwn(string variable)
    {
        Set(variable, "ftp://collector.example:4318");

        var error = Assert.Throws<ConfigurationError>(() => ConfigEnv.ConfigFromEnv());
        Assert.Equal("invalid OTLP endpoint: ftp://collector.example:4318", error.Message);
    }

    [Fact]
    public void Endpoints_PerSignalOverridesLandOnTheirOwnSignal()
    {
        // The premise the theory above depends on: each variable reaches exactly
        // one signal, so a rejection driven through one of them names one of the
        // three validation calls and no other.
        Set("OTEL_EXPORTER_OTLP_ENDPOINT", "http://shared:4318");
        Set("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "http://logs:4318");
        Set("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://traces:4318");

        var config = ConfigEnv.ConfigFromEnv();

        Assert.Equal("http://logs:4318", config.Logging.OtlpEndpoint);
        Assert.Equal("http://traces:4318", config.Tracing.OtlpEndpoint);
        // Metrics has no override of its own, so it inherits the shared value.
        Assert.Equal("http://shared:4318", config.Metrics.OtlpEndpoint);
    }

    // ── RedactConfig ─────────────────────────────────────────────────────────

    [Fact]
    public void RedactConfig_MasksCredentialsEmbeddedInAnEndpoint()
    {
        var config = TelemetryConfig.Default();
        config.Logging.OtlpEndpoint = "https://alice:s3cr3t@collector.example/v1/logs";

        // The user name survives so an operator can tell which credential is in
        // play; only the password goes.
        Assert.Equal(
            "https://alice:****@collector.example/v1/logs",
            Signal(config, "logging")["otlp_endpoint"]);
    }

    [Fact]
    public void RedactConfig_LeavesACredentialFreeEndpointIntact()
    {
        var config = TelemetryConfig.Default();
        config.Tracing.OtlpEndpoint = "https://collector.example:4318";

        Assert.Equal("https://collector.example:4318", Signal(config, "tracing")["otlp_endpoint"]);
    }

    [Fact]
    public void RedactConfig_LeavesAnUnparseableEndpointIntact()
    {
        var config = TelemetryConfig.Default();
        config.Metrics.OtlpEndpoint = "not a uri";

        Assert.Equal("not a uri", Signal(config, "metrics")["otlp_endpoint"]);
    }

    [Fact]
    public void RedactConfig_ShowsAtMostAFourCharacterPrefixOfAHeaderValue()
    {
        var config = TelemetryConfig.Default();
        config.Tracing.OtlpHeaders["Authorization"] = "Bearer averylongtokenvalue";
        config.Tracing.OtlpHeaders["X-Short"] = "abc";

        var headers = Assert.IsType<Dictionary<string, string>>(
            Signal(config, "tracing")["otlp_headers"]);

        Assert.Equal("Bear****", headers["Authorization"]);
        // Anything under eight characters gives away too much as a prefix, so
        // it is masked whole.
        Assert.Equal("****", headers["X-Short"]);
    }

    [Fact]
    public void RedactConfig_CarriesTheIdentityFieldsUnmasked()
    {
        var config = TelemetryConfig.Default();
        config.ServiceName = "svc";
        config.Environment = "prod";
        config.Version = "1.2.3";

        var redacted = ProvideTelemetry.RedactConfig(config);

        Assert.Equal("svc", redacted["service_name"]);
        Assert.Equal("prod", redacted["environment"]);
        Assert.Equal("1.2.3", redacted["version"]);
    }

    [Fact]
    public void RedactConfig_RejectsANullConfig()
    {
        Assert.Throws<ArgumentNullException>(() => ConfigEnv.RedactConfig(null!));
    }

    private static Dictionary<string, object?> Signal(TelemetryConfig config, string signal) =>
        Assert.IsType<Dictionary<string, object?>>(ProvideTelemetry.RedactConfig(config)[signal]);
}
