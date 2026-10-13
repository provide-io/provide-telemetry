// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Globalization;
using System.Text;

using Provide.Telemetry;
using Provide.Telemetry.OpenTelemetry.Prometheus;
using Xunit;

namespace Provide.Telemetry.OpenTelemetry.Tests.Prometheus;

/// <summary>The Tier 2 handler: status per lifecycle state, health families, content negotiation.</summary>
[Collection("OpenTelemetry")]
public sealed class PrometheusEndpointTests : PromTestBase
{
    public static IEnumerable<object[]> HandlerStatus() => PromFixtures.Rows("handler_status");

    private void Enter(string state)
    {
        var config = PromConfig();
        switch (state)
        {
            case "not_set_up":
                return;
            case "shut_down":
                ProvideTelemetry.SetupTelemetry(config);
                ProvideTelemetry.ShutdownTelemetry();
                return;
            case "metrics_disabled":
                config.Metrics.Enabled = false;
                break;
            case "host_provider":
                TelemetryBackendRegistry.MarkHostProviders(metrics: true);
                break;
        }
        ProvideTelemetry.SetupTelemetry(config);
    }

    [Theory]
    [MemberData(nameof(HandlerStatus))]
    public void HandlerStatus_FixtureCase(string id, Dictionary<object, object?> c)
    {
        var state = c.Str("state")!;
        Enter(state);
        var response = PrometheusMetrics.MetricsHandler(c.Str("method") ?? "GET");
        Assert.True(int.Parse(c.Str("status")!, CultureInfo.InvariantCulture) == response.Status, id);
        var contentType = response.Headers.Single(h => h.Key == "Content-Type").Value;
        if (c.Str("content_type_prefix") is { } prefix) Assert.StartsWith(prefix, contentType);
        if (response.Status == 503)
        {
            Assert.Equal(PrometheusEndpoint.Reasons[state] + "\n", Encoding.UTF8.GetString(response.Body));
            Assert.Equal(state, PrometheusEndpoint.Status);
        }
    }

    [Fact]
    public void Status_EachNotReadyStateHasItsOwnOneLineReason()
    {
        Assert.Equal(6, PrometheusEndpoint.Reasons.Values.Distinct().Count());
        Assert.All(PrometheusEndpoint.Reasons.Values, r => Assert.DoesNotContain('\n', r));
        Assert.All(PrometheusEndpoint.Reasons.Values, r => Assert.StartsWith("provide-telemetry: ", r));
    }

    [Fact]
    public void RenderPrometheus_ThrowsTheReasonWhenNotReady()
    {
        var error = Assert.Throws<TelemetryError>(() => PrometheusMetrics.RenderPrometheus());
        Assert.Equal("provide-telemetry: metrics are not set up yet", error.Message);
    }

    [Fact]
    public void NotSelected_WithoutPrometheusInTheExporters()
    {
        var config = PromConfig();
        config.Metrics.Exporters = ["otlp"];
        ProvideTelemetry.SetupTelemetry(config);
        Assert.Equal(PrometheusEndpoint.NotSelected, PrometheusEndpoint.Status);
        Assert.Equal(503, PrometheusMetrics.MetricsHandler("GET").Status);
    }

    [Fact]
    public void Ready_ServesInstrumentsAndHealthWithEachMethod()
    {
        ProvideTelemetry.SetupTelemetry(PromConfig());
        ProvideTelemetry.Counter("app.requests").Add(3, new Dictionary<string, object?> { ["route"] = "/a" });
        ProvideTelemetry.Gauge("app.temperature", unit: "Cel").Set(21.5);
        ProvideTelemetry.Histogram("app.latency", unit: "ms").Record(12);

        var get = PrometheusMetrics.MetricsHandler("GET");
        var body = Encoding.UTF8.GetString(get.Body);
        Assert.Equal(200, get.Status);
        Assert.Equal([new("Content-Type", PrometheusRender.ContentTypeText)], get.Headers);
        Assert.Contains("app_requests_total{route=\"/a\"} 3\n", body);
        Assert.Contains("app_temperature_celsius 21.5\n", body);
        Assert.Contains("app_latency_milliseconds_count 1\n", body);
        Assert.Contains("target_info{", body);
        Assert.Contains("service_name=\"prom-test\"", body);
        Assert.Contains("provide_telemetry_emitted_total{signal=\"metrics\"} 3\n", body);
        Assert.Contains("provide_telemetry_setup_error 0\n", body);
        Assert.Contains("\nprovide_telemetry_receipt_failures_total 0\n", body);
        Assert.Contains("\nprovide_telemetry_reserved_field_replacements_total 0\n", body);

        var head = PrometheusMetrics.MetricsHandler("HEAD");
        Assert.Equal((200, 0), (head.Status, head.Body.Length));

        var post = PrometheusMetrics.MetricsHandler("POST");
        Assert.Equal(405, post.Status);
        Assert.Equal(
            [new("Allow", "GET, HEAD"), new("Content-Type", "text/plain; charset=utf-8")], post.Headers);
        Assert.Equal("method not allowed\n", Encoding.UTF8.GetString(post.Body));
        Assert.Throws<ArgumentNullException>(() => PrometheusMetrics.MetricsHandler(null!));
    }

    [Fact]
    public void Ready_Utf8NamesOnlyForAScraperThatNegotiatesThem()
    {
        var config = PromConfig();
        config.Metrics.Prometheus.Translation = "NoTranslation";
        config.Metrics.Prometheus.ScopeLabels = true;
        config.Metrics.Prometheus.TargetInfo = false;
        ProvideTelemetry.SetupTelemetry(config);
        ProvideTelemetry.Counter("app.requests").Add(1);

        Assert.Contains("\napp_requests 1\n", "\n" + Scrape().Replace("{otel_scope_name=\"Provide.Telemetry\"}", ""));
        var utf8 = PrometheusMetrics.RenderPrometheus("text/plain;version=1.0.0;escaping=allow-utf-8");
        Assert.Equal(PrometheusRender.ContentTypeUtf8, utf8.ContentType);
        Assert.Contains("{\"app.requests\",otel_scope_name=\"Provide.Telemetry\"} 1\n", Encoding.UTF8.GetString(utf8.Body));
        Assert.DoesNotContain("target_info", Scrape());
    }

    [Fact]
    public void Ready_IsCumulativeAcrossScrapes()
    {
        ProvideTelemetry.SetupTelemetry(PromConfig());
        var counter = ProvideTelemetry.Counter("app.hits");
        counter.Add(2);
        Assert.Contains("app_hits_total 2\n", Scrape());
        counter.Add(3);
        Assert.Contains("app_hits_total 5\n", Scrape());
    }

    [Fact]
    public void ListenAlone_AttachesTheReader()
    {
        var config = PromConfig();
        config.Metrics.Exporters = ["otlp"];
        config.Metrics.Prometheus.Listen = "true";
        config.Metrics.Prometheus.Port = 0;
        ProvideTelemetry.SetupTelemetry(config);
        Assert.Equal(PrometheusEndpoint.Ready, PrometheusEndpoint.Status);
    }

    // ── health ───────────────────────────────────────────────────────────────

    private static readonly Dictionary<string, string> SignalPrefix = new()
    {
        ["logs"] = "Logs",
        ["traces"] = "Traces",
        ["metrics"] = "Metrics",
    };

    private static readonly Dictionary<string, string> FieldName = new()
    {
        ["emitted"] = "Emitted",
        ["dropped"] = "Dropped",
        ["export_failures"] = "ExportFailures",
        ["retries"] = "Retries",
        ["export_latency_ms"] = "ExportLatencyMs",
        ["async_blocking_risk"] = "AsyncBlockingRisk",
        ["circuit_state"] = "CircuitState",
        ["circuit_open_count"] = "CircuitOpenCount",
    };

    private static HealthSnapshot Snapshot(Dictionary<object, object?> fields)
    {
        var snapshot = new HealthSnapshot();
        foreach (var (rawKey, rawValue) in fields)
        {
            var key = (string)rawKey;
            var value = (string)rawValue!;
            string property;
            if (key == "setup_error") property = "SetupError";
            else if (key == "receipt_failures") property = "ReceiptFailures";
            else if (key == "reserved_field_replacements") property = "ReservedFieldReplacements";
            else
            {
                var signal = key[(key.LastIndexOf('_') + 1)..];
                property = SignalPrefix[signal] + FieldName[key[..key.LastIndexOf('_')]];
            }
            var info = typeof(HealthSnapshot).GetProperty(property)!;
            info.SetValue(snapshot, Convert.ChangeType(value, info.PropertyType, CultureInfo.InvariantCulture));
        }
        return snapshot;
    }

    public static IEnumerable<object[]> HealthCases() => PromFixtures.Rows("health_metrics");

    [Theory]
    [MemberData(nameof(HealthCases))]
    public void HealthMetrics_FixtureCase(string id, Dictionary<object, object?> c)
    {
        var full = PromFixtures.Section("health_metrics")[0].Map("snapshot")!;
        var fields = new Dictionary<object, object?>(full);
        foreach (var (k, v) in c.Map("snapshot_overrides") ?? []) fields[k] = v;
        var families = PrometheusHealth.Families(Snapshot(fields));
        var actual = families
            .SelectMany(f => f.Samples.Select(s => (f.Name, Labels: string.Join(",", s.Labels.Select(l => $"{l.Key}={l.Value}")), s.Value)))
            .ToList();
        foreach (var sample in ((List<object?>)c["expected_samples"]!).Cast<Dictionary<object, object?>>())
        {
            var labels = string.Join(",", sample.Map("labels")!.Select(l => $"{l.Key}={l.Value}"));
            var want = (sample.Str("metric")!, labels, double.Parse(sample.Str("value")!, CultureInfo.InvariantCulture));
            Assert.True(actual.Contains(want), $"{id}: missing {want}");
        }
        Assert.Equal(27, actual.Count);
        Assert.Equal(
            ["counter", "counter", "counter", "counter", "gauge", "counter", "gauge", "counter", "gauge", "counter", "counter"],
            families.Select(f => f.Kind));
    }

    [Theory]
    [InlineData("closed", 0)]
    [InlineData("half-open", 1)]
    [InlineData("open", 2)]
    [InlineData("unknown", -1)]
    [InlineData("", -1)]
    public void CircuitValue_MapsTheSpecValues(string state, double want) =>
        Assert.Equal(want, PrometheusHealth.CircuitValue(state));
}
