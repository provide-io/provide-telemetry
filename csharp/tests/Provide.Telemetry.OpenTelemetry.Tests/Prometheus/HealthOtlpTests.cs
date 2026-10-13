// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Reflection;

using Provide.Telemetry;
using Provide.Telemetry.OpenTelemetry.Prometheus;
using Xunit;

namespace Provide.Telemetry.OpenTelemetry.Tests.Prometheus;

/// <summary>PROVIDE_METRICS_HEALTH_OTLP: the health families as instruments on our provider.</summary>
[Collection("OpenTelemetry")]
public sealed class HealthOtlpTests : PromTestBase
{
    /// <summary>The pull reader setup attached, read without the renderer's skip list.</summary>
    private static CapturedBatch RawCollection()
    {
        var serving = typeof(PrometheusEndpoint).GetField("_serving", BindingFlags.NonPublic | BindingFlags.Static)!;
        var value = ((PrometheusPullReader Reader, RenderOptions Options)?)serving.GetValue(null);
        return value!.Value.Reader.Snapshot();
    }

    private static TelemetryConfig Config(bool healthOtlp)
    {
        var config = PromConfig();
        config.Metrics.HealthOtlp = healthOtlp;
        return config;
    }

    [Fact]
    public void On_TheProviderCarriesTheTwentySixSeriesWithTheirValues()
    {
        ProvideTelemetry.SetupTelemetry(Config(healthOtlp: true));
        ProvideTelemetry.Counter("app.hits").Add(2);
        var health = RawCollection().Metrics.Where(m => PrometheusHealth.MetricNames.Contains(m.Name)).ToList();

        Assert.Equal(11, health.Count);
        Assert.Equal(27, health.Sum(m => m.Points.Count));
        Assert.All(health, m => Assert.Equal(("", ""), (m.Unit, m.Description)));
        var emitted = health.Single(m => m.Name == "provide_telemetry_emitted_total");
        Assert.Equal(PrometheusNames.MonotonicCounter, emitted.Kind);
        var metricsPoint = emitted.Points.Single(p => p.Attributes.SequenceEqual([new KeyValuePair<string, object?>("signal", "metrics")]));
        Assert.Equal(1, metricsPoint.Value); // one Add, however large
        var circuit = health.Single(m => m.Name == "provide_telemetry_circuit_state");
        Assert.Equal(PrometheusNames.Gauge, circuit.Kind);
        Assert.All(circuit.Points, p => Assert.Equal(0, p.Value));
        var setupError = health.Single(m => m.Name == "provide_telemetry_setup_error");
        Assert.Empty(Assert.Single(setupError.Points).Attributes);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void Scrape_CarriesEachHealthFamilyExactlyOnce(bool healthOtlp)
    {
        ProvideTelemetry.SetupTelemetry(Config(healthOtlp));
        var body = Scrape();
        foreach (var name in PrometheusHealth.MetricNames)
        {
            Assert.Equal(1, body.Split($"# TYPE {name} ").Length - 1);
        }
        Assert.Equal(healthOtlp, RawCollection().Metrics.Any(m => PrometheusHealth.MetricNames.Contains(m.Name)));
    }

    [Fact]
    public void Collections_DoNotCountAsEmittedAndIgnoreConsent()
    {
        ProvideTelemetry.SetupTelemetry(Config(healthOtlp: true));
        ProvideTelemetry.SetConsentLevel(ConsentLevel.None);
        var before = ProvideTelemetry.GetHealthSnapshot().MetricsEmitted;
        var first = RawCollection();
        RawCollection();
        Assert.Equal(before, ProvideTelemetry.GetHealthSnapshot().MetricsEmitted);
        Assert.Equal(27, first.Metrics.Where(m => PrometheusHealth.MetricNames.Contains(m.Name)).Sum(m => m.Points.Count));
    }

    [Fact]
    public void SetupErrorIsReadFreshAtEachCollection()
    {
        ProvideTelemetry.SetupTelemetry(Config(healthOtlp: true));
        double SetupError() => RawCollection().Metrics.Single(m => m.Name == "provide_telemetry_setup_error").Points[0].Value;
        Assert.Equal(0, SetupError());
        Health.SetSetupError("boom");
        Assert.Equal(1, SetupError());
    }

    [Fact]
    public void Render_SkipsTheNamedInstruments()
    {
        var batch = new CapturedBatch([],
        [
            new("provide_telemetry_setup_error", "", "", PrometheusNames.Gauge, "s", null, [new([], 1)]),
            new("kept", "", "", PrometheusNames.Gauge, "s", null, [new([], 1)]),
        ]);
        var options = new RenderOptions("UnderscoreEscapingWithSuffixes") { Skip = PrometheusHealth.MetricNames };
        Assert.Equal(["kept"], PrometheusRender.FamiliesFrom(batch, options).Select(f => f.Name));
        Assert.Equal(2, PrometheusRender.FamiliesFrom(batch, new RenderOptions("UnderscoreEscapingWithSuffixes")).Count);
        Assert.Equal(11, PrometheusHealth.MetricNames.Count);
    }
}
