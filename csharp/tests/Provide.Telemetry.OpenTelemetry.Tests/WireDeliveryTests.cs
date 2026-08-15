// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.OpenTelemetry.Tests;

/// <summary>
/// Asserts what actually reaches an OTLP endpoint. Everything here was
/// previously unobservable — the SDK exposes none of it after Build() — which
/// is exactly where the surviving mutants lived: per-signal URL paths, the
/// formatted header string, the exporter option booleans, the SLO metric
/// names, and whether shutdown drains at all.
/// </summary>
[Collection("OpenTelemetry")]
public sealed class WireDeliveryTests : IDisposable
{
    private readonly FakeOtlpCollector _collector = new();
    private static readonly TimeSpan Wait = TimeSpan.FromSeconds(10);

    public WireDeliveryTests()
    {
        Testing.ResetForTests();
        OpenTelemetryBackendRegistration.Register();
    }

    public void Dispose()
    {
        Testing.ResetForTests();
        _collector.Dispose();
    }

    private TelemetryConfig WiredConfig()
    {
        var config = TelemetryConfig.Default();
        config.ServiceName = "wire-svc";
        config.Logging.OtlpEnabled = true;
        config.Logging.OtlpEndpoint = _collector.Endpoint;
        config.Logging.OtlpHeaders["api-key"] = "wire-secret-token";
        config.Tracing.OtlpEndpoint = _collector.Endpoint;
        config.Metrics.OtlpEndpoint = _collector.Endpoint;
        return config;
    }

    [Fact]
    public void EachSignalDeliversToItsOwnPathWithTheConfiguredHeader()
    {
        ProvideTelemetry.SetupTelemetry(WiredConfig());
        try
        {
            ProvideTelemetry.GetLogger("wire").Info("wire.deliver.ok");
            ProvideTelemetry.Trace("wire.span.ok", () => { });
            ProvideTelemetry.Counter("wire.count").Add(1);
            ProvideTelemetry.FlushTelemetry(TimeSpan.FromSeconds(5));
        }
        finally
        {
            ProvideTelemetry.ShutdownTelemetry();
        }

        var logs = _collector.WaitFor("/v1/logs", Wait);
        var traces = _collector.WaitFor("/v1/traces", Wait);
        var metrics = _collector.WaitFor("/v1/metrics", Wait);

        Assert.NotNull(logs);
        Assert.NotNull(traces);
        Assert.NotNull(metrics);
        // The formatted header string must land as a real HTTP header on
        // the logs exporter, which carries the configured headers.
        Assert.Equal("wire-secret-token", logs!.Headers["api-key"]);
    }

    [Fact]
    public void TheLogExportCarriesMessageScopeAttributesAndService()
    {
        ProvideTelemetry.SetupTelemetry(WiredConfig());
        try
        {
            ProvideTelemetry.GetLogger("wire").Info(
                "wire.body.ok", new Dictionary<string, object?> { ["order_id"] = "ord-77" });
            ProvideTelemetry.FlushTelemetry(TimeSpan.FromSeconds(5));
        }
        finally
        {
            ProvideTelemetry.ShutdownTelemetry();
        }

        var logs = _collector.WaitFor("/v1/logs", Wait);

        Assert.NotNull(logs);
        // IncludeFormattedMessage: the event text is in the body.
        Assert.True(logs!.BodyContains("wire.body.ok"));
        // IncludeScopes + ParseStateValues: the scope attribute key and
        // value from the canonical record's vocabulary are in the body.
        Assert.True(logs.BodyContains("order_id"));
        Assert.True(logs.BodyContains("ord-77"));
        // Resource: the configured service name rode along.
        Assert.True(logs.BodyContains("wire-svc"));
    }

    [Fact]
    public void TheSloMetricNamesAreRealOnTheWire()
    {
        ProvideTelemetry.SetupTelemetry(WiredConfig());
        try
        {
            Slo.RecordRedMetrics("checkout", 12.5, success: true);
            Slo.RecordUseMetrics("cpu", 0.5, 0.1, 0);
            ProvideTelemetry.FlushTelemetry(TimeSpan.FromSeconds(5));
        }
        finally
        {
            ProvideTelemetry.ShutdownTelemetry();
        }

        var metrics = _collector.WaitFor("/v1/metrics", Wait);

        Assert.NotNull(metrics);
        var body = _collector.RequestsTo("/v1/metrics");
        bool OnWire(string name) => body.Any(r => r.BodyContains(name));
        Assert.True(OnWire("provide.slo.red.requests"));
        Assert.True(OnWire("provide.slo.red.duration_ms"));
        Assert.True(OnWire("provide.slo.use.utilization"));
        Assert.True(OnWire("provide.slo.use.saturation"));
        Assert.True(OnWire("provide.slo.use.errors"));
    }

    [Fact]
    public void ShutdownAloneDrainsTheBatchedSpanToTheWire()
    {
        ProvideTelemetry.SetupTelemetry(WiredConfig());
        ProvideTelemetry.Trace("wire.drain.ok", () => { });
        // No explicit flush: the batch processor holds the span until the
        // teardown drain runs. A deleted Shutdown call in DisposeDetached
        // means this capture stays empty.
        ProvideTelemetry.ShutdownTelemetry();

        Assert.NotNull(_collector.WaitFor("/v1/traces", Wait));
    }
}
