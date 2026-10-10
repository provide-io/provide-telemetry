// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.OpenTelemetry.Tests.Prometheus;

/// <summary>Observable instruments per prometheus_metrics.observable_instruments.</summary>
[Collection("OpenTelemetry")]
public sealed class ObservableInstrumentTests : PromTestBase
{
    private static IEnumerable<Observation> One(double value, string? key = null) =>
        [new Observation(value, key is null ? null : new Dictionary<string, object?> { ["k"] = key })];

    [Fact]
    public void BeforeSetup_TheHandleIsInertAndUnregisterIsANoOp()
    {
        var calls = 0;
        // No backend registered for this lifecycle: the fallback meter has no observables.
        var config = TelemetryConfig.Default();
        config.Metrics.Enabled = false;
        ProvideTelemetry.SetupTelemetry(config);
        var handle = ProvideTelemetry.ObservableGauge("g", () => { calls++; return One(1); });
        Assert.False(handle.Registered);
        Assert.Equal("g", handle.Name);
        handle.Unregister();
        handle.Unregister();
        Assert.Empty(handle.Collect());
        Assert.Equal(0, calls);
        Assert.False(ProvideTelemetry.ObservableCounter("c", () => One(1)).Registered);
        Assert.False(ProvideTelemetry.ObservableUpDownCounter("u", () => One(1)).Registered);
    }

    [Fact]
    public void AfterSetup_EachKindIsScrapedAndUnregisterRemovesIt()
    {
        ProvideTelemetry.SetupTelemetry(PromConfig());
        var gauge = ProvideTelemetry.ObservableGauge("device.temperature", () => One(41.5, "a"), "temp", "Cel");
        var counter = ProvideTelemetry.ObservableCounter("process.cpu.time", () => One(7), unit: "s");
        var updown = ProvideTelemetry.ObservableUpDownCounter("pool.connections", () => One(-2));
        Assert.True(gauge.Registered && counter.Registered && updown.Registered);

        var body = Scrape();
        Assert.Contains("# HELP device_temperature_celsius temp\n", body);
        Assert.Contains("device_temperature_celsius{k=\"a\"} 41.5\n", body);
        Assert.Contains("# TYPE process_cpu_time_seconds_total counter\nprocess_cpu_time_seconds_total 7\n", body);
        Assert.Contains("# TYPE pool_connections gauge\npool_connections -2\n", body);

        gauge.Unregister();
        gauge.Unregister();
        Assert.False(gauge.Registered);
        Assert.DoesNotContain("device_temperature_celsius{", Scrape());
    }

    [Fact]
    public void Observations_CountAsEmittedButAreNotSampled()
    {
        var config = PromConfig();
        config.Sampling.MetricsRate = 0;
        ProvideTelemetry.SetupTelemetry(config);
        ProvideTelemetry.ObservableGauge("g", () => [new Observation(1), new Observation(2, new Dictionary<string, object?> { ["x"] = "y" })]);
        var before = ProvideTelemetry.GetHealthSnapshot().MetricsEmitted;
        Assert.Contains("g{x=\"y\"} 2\n", Scrape());
        Assert.Equal(before + 2, ProvideTelemetry.GetHealthSnapshot().MetricsEmitted);
    }

    [Fact]
    public void ConsentNone_ObservesNothing()
    {
        ProvideTelemetry.SetupTelemetry(PromConfig());
        var calls = 0;
        ProvideTelemetry.ObservableGauge("g", () => { calls++; return One(1); });
        ProvideTelemetry.SetConsentLevel(ConsentLevel.None);
        Assert.DoesNotContain("\ng ", Scrape());
        Assert.Equal(0, calls);
        ProvideTelemetry.SetConsentLevel(ConsentLevel.Functional);
        Assert.Contains("\ng 1\n", Scrape());
    }

    [Fact]
    public void MetricsDisabled_ObservesNothing()
    {
        var config = TelemetryConfig.Default();
        config.Metrics.Enabled = false;
        ProvideTelemetry.SetupTelemetry(config);
        var handle = new ObservableInstrument("g", () => One(1));
        handle.Attach();
        Assert.Empty(handle.Collect());
    }

    [Fact]
    public void AFailingCallback_ContributesNothingAndWarnsOncePerInstrument()
    {
        ProvideTelemetry.SetupTelemetry(PromConfig());
        ProvideTelemetry.ObservableGauge("bad", () => throw new InvalidOperationException("boom"));
        ProvideTelemetry.ObservableGauge("lazy.bad", () => Fail());
        ProvideTelemetry.ObservableGauge("good", () => One(1));
        var stderr = StderrOf(() =>
        {
            Assert.Contains("\ngood 1\n", Scrape());
            Assert.Contains("\ngood 1\n", Scrape());
        })!;
        Assert.Equal(2, stderr.Split("metrics.observable_callback_failed").Length - 1);
        Assert.Contains("boom", stderr);
        Assert.Contains("lazy", stderr);
        Assert.DoesNotContain("\nbad ", Scrape());

        static IEnumerable<Observation> Fail()
        {
            yield return new Observation(1);
            throw new InvalidOperationException("lazy");
        }
    }

    [Fact]
    public void Handle_RejectsNulls()
    {
        Assert.Throws<ArgumentNullException>(() => new ObservableInstrument(null!, () => []));
        Assert.Throws<ArgumentNullException>(() => new ObservableInstrument("x", null!));
    }
}
