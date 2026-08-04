// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

[Collection("Telemetry")]
public class LifecycleTests
{
    public LifecycleTests() => Testing.ResetForTests();

    [Fact]
    public void Setup_Idempotent()
    {
        var a = ProvideTelemetry.SetupTelemetry();
        var b = ProvideTelemetry.SetupTelemetry();
        Assert.Equal(a.ServiceName, b.ServiceName);
        Assert.True(ProvideTelemetry.GetRuntimeStatus().SetupDone);
    }

    [Fact]
    public void RuntimeFacade_StartFlushShutdown()
    {
        var rt = new TelemetryRuntime();
        var cfg = rt.Start();
        Assert.NotNull(cfg);
        var logger = rt.GetLogger("facade");
        Assert.NotNull(logger);
        var counter = ProvideTelemetry.Counter("test.counter");
        counter.Add(3);
        Assert.Equal(3, counter.Value);
        var flush = rt.Flush();
        Assert.NotNull(flush);
        rt.Shutdown();
        Assert.False(ProvideTelemetry.GetRuntimeStatus().SetupDone);
    }

    [Fact]
    public void Metrics_Instruments()
    {
        ProvideTelemetry.SetupTelemetry();
        var c = ProvideTelemetry.Counter("c1");
        c.Add(2);
        Assert.Equal(2, c.Value);
        var g = ProvideTelemetry.Gauge("g1");
        g.Set(1.5);
        Assert.Equal(1.5, g.Value);
        var h = ProvideTelemetry.Histogram("h1");
        h.Record(4);
        h.Record(6);
        Assert.Equal(2, h.Count);
        Assert.Equal(10, h.Sum);
    }

    [Fact]
    public void Tracer_StartsSpan()
    {
        ProvideTelemetry.SetupTelemetry();
        using var span = ProvideTelemetry.GetTracer().StartSpan("work");
        Assert.False(string.IsNullOrEmpty(span.TraceId));
        Assert.Equal(32, span.TraceId.Length);
        Assert.Equal(16, span.SpanId.Length);
    }

    [Fact]
    public void Governance_ClassificationAndConsent()
    {
        ProvideTelemetry.RegisterClassificationRule(new ClassificationRule
        {
            Pattern = "ssn",
            Class = DataClass.Restricted,
        });
        Assert.Equal(DataClass.Restricted, ProvideTelemetry.ClassifyKey("ssn"));
        ProvideTelemetry.SetConsentLevel(ConsentLevel.None);
        Assert.False(ProvideTelemetry.ShouldAllow("logs", "INFO"));
        ProvideTelemetry.SetConsentLevel(ConsentLevel.Full);
        Assert.True(ProvideTelemetry.ShouldAllow("logs", "INFO"));
        ProvideTelemetry.EnableReceipts(true, "key", "svc");
        var redacted = ProvideTelemetry.RedactConfig(TelemetryConfig.Default());
        Assert.Equal("provide-service", redacted["service_name"]);
    }
}
