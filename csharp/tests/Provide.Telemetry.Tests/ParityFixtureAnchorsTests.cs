// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// Explicit fixture-category coverage anchors. Names and assertions map 1:1 to
/// categories in spec/behavioral_fixtures.yaml so check_fixture_coverage.py
/// attributes them to C#.
/// </summary>
[Collection("Telemetry")]
public class ParityFixtureAnchorsTests
{
    public ParityFixtureAnchorsTests() => Testing.ResetForTests();

    [Fact]
    public void PropagationGuards_OversizedTraceparentDiscarded()
    {
        var huge = "00-" + new string('a', 600) + "-b7ad6b7169203331-01";
        var pc = ProvideTelemetry.ExtractW3CContext(new Dictionary<string, string> { ["traceparent"] = huge });
        Assert.Equal("", pc.Traceparent);
    }

    [Fact]
    public void PropagationOversizedTraceparent_IsEmpty()
    {
        var huge = new string('x', 600);
        var pc = ProvideTelemetry.ExtractW3CContext(new Dictionary<string, string> { ["traceparent"] = huge });
        Assert.Equal("", pc.TraceID);
    }

    [Fact]
    public void DefaultSensitiveKeys_PasswordRedacted()
    {
        var r = Pii.SanitizePayload(new Dictionary<string, object?> { ["password"] = "x" }, true, 8);
        Assert.Equal("***", r["password"]);
    }

    [Fact]
    public void ErrorFingerprint_ClassifyTimeout()
    {
        Assert.Equal("timeout", Slo.ClassifyError(new TimeoutException("slow")));
    }

    [Fact]
    public void SamplingSignalValidation_RejectsUnknown()
    {
        Assert.Throws<ConfigurationError>(() =>
            ProvideTelemetry.SetSamplingPolicy("not-a-signal", new SamplingPolicy()));
    }

    [Fact]
    public void SamplingRateBounds_ClampsHigh()
    {
        var p = ProvideTelemetry.SetSamplingPolicy("logs", new SamplingPolicy { DefaultRate = 99 });
        Assert.Equal(1.0, p.DefaultRate);
    }

    [Fact]
    public void CardinalitySaturation_Overflow()
    {
        ProvideTelemetry.ClearCardinalityLimits();
        ProvideTelemetry.RegisterCardinalityLimit("k", new CardinalityLimit { MaxValues = 1, TtlSeconds = 60 });
        _ = ProvideTelemetry.GuardAttributes(new Dictionary<string, string> { ["k"] = "a" });
        var overflow = ProvideTelemetry.GuardAttributes(new Dictionary<string, string> { ["k"] = "b" });
        Assert.Equal("__overflow__", overflow["k"]);
    }
}
