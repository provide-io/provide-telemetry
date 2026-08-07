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

    [Fact]
    public void ConfigHeaders_Parsing()
    {
        Environment.SetEnvironmentVariable("PROVIDE_TRACE_OTLP_HEADERS", "Authorization=Bearer abc,X-Custom=1");
        try
        {
            Testing.ResetForTests();
            var cfg = ConfigEnv.ConfigFromEnv();
            Assert.Equal("Bearer abc", cfg.Tracing.OtlpHeaders["Authorization"]);
            Assert.Equal("1", cfg.Tracing.OtlpHeaders["X-Custom"]);
        }
        finally
        {
            Environment.SetEnvironmentVariable("PROVIDE_TRACE_OTLP_HEADERS", null);
        }
    }

    [Fact]
    public void EndpointValidation_Invalid()
    {
        Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", "ftp://collector.example/otlp");
        try
        {
            Testing.ResetForTests();
            Assert.Throws<ConfigurationError>(() => ConfigEnv.ConfigFromEnv());
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
            Assert.Contains("\"service.name\":\"parity-svc\"", line);
            Assert.Contains("\"trace.id\":\"0af7651916cd43dd8448eb211c80319c\"", line);
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
