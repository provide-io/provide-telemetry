// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

[Collection("Telemetry")]
public class ParityOtherTests
{
    public ParityOtherTests() => Testing.ResetForTests();

    [Fact]
    public void Backpressure_Unlimited_ZeroSize()
    {
        ProvideTelemetry.SetQueuePolicy(new QueuePolicy());
        for (var i = 0; i < 100; i++)
        {
            var t = Backpressure.TryAcquire("logs");
            Assert.NotNull(t);
            Backpressure.Release(t);
        }
    }

    [Fact]
    public void Cardinality_Clamping()
    {
        ProvideTelemetry.RegisterCardinalityLimit("route", new CardinalityLimit { MaxValues = 2, TtlSeconds = 300 });
        var a = ProvideTelemetry.GuardAttributes(new Dictionary<string, string> { ["route"] = "/a" });
        var b = ProvideTelemetry.GuardAttributes(new Dictionary<string, string> { ["route"] = "/b" });
        var c = ProvideTelemetry.GuardAttributes(new Dictionary<string, string> { ["route"] = "/c" });
        Assert.Equal("/a", a["route"]);
        Assert.Equal("/b", b["route"]);
        Assert.Equal("__overflow__", c["route"]);
    }

    [Fact]
    public void HealthSnapshot_Canonical()
    {
        var h = ProvideTelemetry.GetHealthSnapshot();
        Assert.Equal("closed", h.LogsCircuitState);
        Assert.Equal("", h.SetupError);
    }

    [Fact]
    public void SloClassify()
    {
        Assert.Equal("timeout", Slo.ClassifyError(new TimeoutException()));
        Assert.Equal("config", Slo.ClassifyError(new ConfigurationError("x")));
    }

    [Theory]
    // spec/behavioral_fixtures.yaml config_headers, case for case.
    [InlineData("Authorization=Bearer+token", "Authorization", "Bearer+token")]
    [InlineData("my%20key=my%20value", "my key", "my value")]
    [InlineData("=value,key=val", "key", "val")]
    [InlineData("malformed,key=val", "key", "val")]
    [InlineData("Authorization=Bearer token=xyz", "Authorization", "Bearer token=xyz")]
    [InlineData("a+b=c+d", "a+b", "c+d")]
    [InlineData("a%20b=c%20d", "a b", "c d")]
    public void ConfigHeaders_Parsing(string raw, string key, string value)
    {
        Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_HEADERS", raw);
        try
        {
            Testing.ResetForTests();
            var cfg = ConfigEnv.ConfigFromEnv();
            // A '+' is a legal token character and must survive verbatim; only
            // %HH sequences decode. The shared header list feeds all three
            // signals, so all three must agree.
            Assert.Equal(value, cfg.Tracing.OtlpHeaders[key]);
            Assert.Equal(value, cfg.Logging.OtlpHeaders[key]);
            Assert.Equal(value, cfg.Metrics.OtlpHeaders[key]);
        }
        finally
        {
            Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_HEADERS", null);
        }
    }

    [Fact]
    public void ConfigHeaders_EmptyStringYieldsNoHeaders()
    {
        Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_HEADERS", "");
        try
        {
            Testing.ResetForTests();
            Assert.Empty(ConfigEnv.ConfigFromEnv().Tracing.OtlpHeaders);
        }
        finally
        {
            Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_HEADERS", null);
        }
    }

    // spec/behavioral_fixtures.yaml endpoint_validation. The seven "valid"
    // endpoints must all survive parsing; of the "invalid" ones this layer
    // rejects the schemes an OTLP client could never speak, and echoes the value
    // so an operator can see which of the three endpoints failed and why. The
    // shape and port cases in that fixture are not enforced here — see the
    // known-gap test below.
    [Theory]
    [InlineData("http://localhost:4318")]
    [InlineData("https://collector.example.com")]
    [InlineData("http://host:4318/v1/traces")]
    [InlineData("http://host")]
    [InlineData("http://[::1]:4318")]
    [InlineData("http://[::1]")]
    [InlineData("https://otel.example.com:4317/v1/metrics")]
    public void EndpointValidation_Valid(string endpoint)
    {
        Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint);
        try
        {
            Testing.ResetForTests();
            Assert.Equal(endpoint, ConfigEnv.ConfigFromEnv().Tracing.OtlpEndpoint);
        }
        finally
        {
            Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", null);
        }
    }

    [Theory]
    [InlineData("ftp://collector.example/otlp")]
    [InlineData("file:///tmp/spans")]
    public void EndpointValidation_Invalid(string endpoint)
    {
        Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint);
        try
        {
            Testing.ResetForTests();
            var error = Assert.Throws<ConfigurationError>(() => ConfigEnv.ConfigFromEnv());
            Assert.Equal($"invalid OTLP endpoint: {endpoint}", error.Message);
        }
        finally
        {
            Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", null);
        }
    }

    [Theory]
    // Parsing soft-validates on purpose, and this pins that it keeps doing so.
    // A value that is not a URI at all, or whose port is malformed, is carried
    // through the config layer unchanged and refused later, at exporter
    // construction, via the exporter's fail-open path. Python behaves
    // identically: validate_otlp_endpoint guards the exporter, not
    // TelemetryConfig.from_env, which accepts every string below.
    //
    // All four are refused by Endpoints.BuildSignalUri — see
    // MalformedEndpointsAreRefusedAtExporterConstruction, which covers the same
    // shapes at the layer that is supposed to catch them.
    [InlineData("not-a-url")]
    [InlineData("http://host:bad")]
    [InlineData("http://host:0")]
    [InlineData("http://host:")]
    public void EndpointValidation_KnownGap_MalformedShapesSurviveParsing(string endpoint)
    {
        Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint);
        try
        {
            Testing.ResetForTests();
            Assert.Equal(endpoint, ConfigEnv.ConfigFromEnv().Tracing.OtlpEndpoint);
        }
        finally
        {
            Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", null);
        }
    }

    [Fact]
    public void ResourcePrecedence_ServiceNameFromEnv()
    {
        Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", "from-env");
        try
        {
            Testing.ResetForTests();
            var cfg = ProvideTelemetry.SetupTelemetry();
            Assert.Equal("from-env", cfg.ServiceName);
        }
        finally
        {
            Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", null);
            Testing.ResetForTests();
        }
    }

    [Fact]
    public void LogOutputFormat_JsonEnvelope()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");
        Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", "parity-svc");
        Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_ENV", "test");
        Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_VERSION", "0.6.0");
        Environment.SetEnvironmentVariable("PROVIDE_LOG_INCLUDE_TIMESTAMP", "false");
        try
        {
            Testing.ResetForTests();
            ProvideTelemetry.SetupTelemetry();
            ProvideTelemetry.SetTraceContext("0af7651916cd43dd8448eb211c80319c", "b7ad6b7169203331");
            var sw = new StringWriter();
            var orig = Console.Error;
            Console.SetError(sw);
            ProvideTelemetry.GetLogger("probe").Info("log.output.parity");
            Console.SetError(orig);
            var line = sw.ToString().Trim().Split('\n').Last(l => l.TrimStart().StartsWith('{'));
            Assert.Contains("\"message\":\"log.output.parity\"", line);
            Assert.Contains("\"level\":\"INFO\"", line);
            Assert.Contains("\"logger_name\":\"probe\"", line);
            // Canonical snake_case identity, per log_output_format in
            // spec/behavioral_fixtures.yaml. The dotted spellings are listed
            // there as noise to be stripped, and no longer appear at all.
            Assert.Contains("\"service\":\"parity-svc\"", line);
            Assert.Contains("\"env\":\"test\"", line);
            Assert.Contains("\"version\":\"0.6.0\"", line);
            Assert.Contains("\"trace_id\":\"0af7651916cd43dd8448eb211c80319c\"", line);
            Assert.Contains("\"span_id\":\"b7ad6b7169203331\"", line);
            Assert.DoesNotContain("service.name", line);
            Assert.DoesNotContain("trace.id", line);
        }
        finally
        {
            foreach (var k in new[] {
                "PROVIDE_LOG_FORMAT", "PROVIDE_TELEMETRY_SERVICE_NAME", "PROVIDE_TELEMETRY_ENV",
                "PROVIDE_TELEMETRY_VERSION", "PROVIDE_LOG_INCLUDE_TIMESTAMP" })
                Environment.SetEnvironmentVariable(k, null);
            Testing.ResetForTests();
        }
    }
}

/// <summary>
/// Fixture categories whose evidence is the fixture's own data, not a
/// representative example: <c>cardinality_saturation</c> and
/// <c>error_fingerprint</c>.
/// </summary>
[Collection("Telemetry")]
public class ParityFixtureDataTests
{
    public ParityFixtureDataTests() => Testing.ResetForTests();

    // ── cardinality_saturation ───────────────────────────────────────────────

    [Fact]
    public void CardinalitySaturation_FixtureSequence_OverflowsOnFourthValue()
    {
        // spec/behavioral_fixtures.yaml: key "route", max_values 3, ttl 300,
        // values /a /b /c /d -> the first three pass through, /d saturates.
        ProvideTelemetry.ClearCardinalityLimits();
        ProvideTelemetry.RegisterCardinalityLimit(
            "route", new CardinalityLimit { MaxValues = 3, TtlSeconds = 300.0 });

        var observed = new List<string>();
        foreach (var value in new[] { "/a", "/b", "/c", "/d" })
        {
            var guarded = ProvideTelemetry.GuardAttributes(
                new Dictionary<string, string> { ["route"] = value });
            observed.Add(guarded["route"]);
        }

        Assert.Equal(new[] { "/a", "/b", "/c", "__overflow__" }, observed);
    }

    [Fact]
    public void CardinalitySaturation_IsDeterministic()
    {
        // "Every call must observe the sentinel deterministically — no sampling,
        // no probabilistic behavior."
        ProvideTelemetry.ClearCardinalityLimits();
        ProvideTelemetry.RegisterCardinalityLimit(
            "route", new CardinalityLimit { MaxValues = 1, TtlSeconds = 300.0 });
        _ = ProvideTelemetry.GuardAttributes(new Dictionary<string, string> { ["route"] = "/a" });

        for (var i = 0; i < 10; i++)
        {
            var guarded = ProvideTelemetry.GuardAttributes(
                new Dictionary<string, string> { ["route"] = "/b" });
            Assert.Equal("__overflow__", guarded["route"]);
        }
    }

    // ── error_fingerprint ────────────────────────────────────────────────────

    [Fact]
    public void ErrorFingerprint_NoFrames_MatchesCanonicalDigest()
    {
        // The fixture pins the cross-language digest: sha256("valueerror")[:12].
        // Python, TypeScript, Go and Rust all produce this exact value.
        var fingerprint = Fingerprint.ComputeErrorFingerprint("ValueError");
        Assert.Equal("a50aba76697e", fingerprint);
        Assert.Equal(12, fingerprint.Length);
    }

    [Fact]
    public void ErrorFingerprint_OneFrame_IsTwelveHexChars()
    {
        var fingerprint = Fingerprint.ComputeErrorFingerprintFromParts(
            "TypeError", new[] { "module:main" });
        Assert.Equal("49f2403c8009", fingerprint);
        Assert.Equal(12, fingerprint.Length);
    }

    [Fact]
    public void ErrorFingerprint_IsCaseInsensitiveOnTypeName()
    {
        Assert.Equal(
            Fingerprint.ComputeErrorFingerprint("VALUEERROR"),
            Fingerprint.ComputeErrorFingerprint("valueerror"));
    }

    [Fact]
    public void ErrorFingerprint_DiffersByExceptionType()
    {
        Assert.NotEqual(
            Fingerprint.ComputeErrorFingerprint("ValueError"),
            Fingerprint.ComputeErrorFingerprint("TypeError"));
    }

    [Fact]
    public void ErrorFingerprint_NormalizesFramesToBasenameAndFunction()
    {
        var stack = "   at Provide.Telemetry.Tests.Widget.Explode() in /src/deep/Widget.cs:line 42";
        Assert.Equal(new[] { "widget:explode" }, Fingerprint.ExtractFrames(stack));
    }

    [Fact]
    public void ErrorFingerprint_KeepsAtMostThreeFrames()
    {
        var stack = string.Join("\n", Enumerable.Range(0, 6).Select(
            i => $"   at Ns.Type.M{i}() in /src/F{i}.cs:line {i}"));
        Assert.Equal(3, Fingerprint.ExtractFrames(stack).Count);
    }

    [Fact]
    public void ErrorFingerprint_IgnoresFramesWithoutFileInfo()
    {
        // Release builds without a PDB emit "at Ns.Type.Method()" and nothing more;
        // a frame with no file contributes no basename and is skipped.
        Assert.Empty(Fingerprint.ExtractFrames("   at Ns.Type.Method()"));
    }

    [Fact]
    public void ErrorFingerprint_FromException_UsesTypeName()
    {
        Exception thrown;
        try { throw new InvalidOperationException("boom"); }
        catch (InvalidOperationException caught) { thrown = caught; }
        Assert.Equal(
            Fingerprint.ComputeErrorFingerprint(thrown),
            Fingerprint.ComputeErrorFingerprint("InvalidOperationException", thrown.StackTrace));
    }

    [Fact]
    public void ErrorFingerprint_NullAndEmptyStacks_MatchNoFrames()
    {
        var bare = Fingerprint.ComputeErrorFingerprint("ValueError");
        Assert.Equal(bare, Fingerprint.ComputeErrorFingerprint("ValueError", null));
        Assert.Equal(bare, Fingerprint.ComputeErrorFingerprint("ValueError", ""));
    }
}
