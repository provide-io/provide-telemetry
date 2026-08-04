// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

[Collection("Telemetry")]
public class ParitySamplingTests
{
    public ParitySamplingTests() => Testing.ResetForTests();

    [Fact]
    public void Sampling_RateZero_AlwaysDrops()
    {
        ProvideTelemetry.SetSamplingPolicy("logs", new SamplingPolicy { DefaultRate = 0.0 });
        for (var i = 0; i < 100; i++)
            Assert.False(ProvideTelemetry.ShouldSample("logs", "evt"));
    }

    [Fact]
    public void Sampling_RateOne_AlwaysKeeps()
    {
        ProvideTelemetry.SetSamplingPolicy("logs", new SamplingPolicy { DefaultRate = 1.0 });
        for (var i = 0; i < 100; i++)
            Assert.True(ProvideTelemetry.ShouldSample("logs", "evt"));
    }

    [Fact]
    public void Sampling_RateHalf_Statistical()
    {
        ProvideTelemetry.SetSamplingPolicy("logs", new SamplingPolicy { DefaultRate = 0.5 });
        var count = 0;
        const int n = 10000;
        for (var i = 0; i < n; i++)
            if (ProvideTelemetry.ShouldSample("logs", "evt")) count++;
        var pct = count * 100.0 / n;
        Assert.InRange(pct, 40, 60);
    }

    [Theory]
    [InlineData("log")]
    [InlineData("trace")]
    [InlineData("metric")]
    [InlineData("events")]
    [InlineData("")]
    public void Sampling_InvalidSignalErrors(string sig)
    {
        Assert.Throws<ConfigurationError>(() =>
            ProvideTelemetry.SetSamplingPolicy(sig, new SamplingPolicy { DefaultRate = 1.0 }));
    }

    [Theory]
    [InlineData("logs")]
    [InlineData("traces")]
    [InlineData("metrics")]
    public void Sampling_ValidSignalsAccepted(string sig)
    {
        var p = ProvideTelemetry.SetSamplingPolicy(sig, new SamplingPolicy { DefaultRate = 0.7 });
        Assert.Equal(0.7, p.DefaultRate, 5);
    }

    [Fact]
    public void Sampling_RateBounds_Clamped()
    {
        var p = ProvideTelemetry.SetSamplingPolicy("logs", new SamplingPolicy { DefaultRate = 2.5 });
        Assert.Equal(1.0, p.DefaultRate);
        p = ProvideTelemetry.SetSamplingPolicy("logs", new SamplingPolicy { DefaultRate = -1 });
        Assert.Equal(0.0, p.DefaultRate);
    }
}
