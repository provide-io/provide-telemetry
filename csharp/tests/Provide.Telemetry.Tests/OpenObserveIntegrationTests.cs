// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// Live OpenObserve integration: export traces/metrics/logs over OTLP HTTP
/// and verify ingestion (mirrors e2e/test_openobserve_e2e.py).
/// Skips only when OPENOBSERVE_* env vars are unset.
/// </summary>
[Collection("Telemetry")]
public class OpenObserveIntegrationTests
{
    private static string? Url => Environment.GetEnvironmentVariable("OPENOBSERVE_URL");
    private static string? User => Environment.GetEnvironmentVariable("OPENOBSERVE_USER");
    private static string? Password => Environment.GetEnvironmentVariable("OPENOBSERVE_PASSWORD");

    private static bool HasEnv =>
        !string.IsNullOrWhiteSpace(Url) &&
        !string.IsNullOrWhiteSpace(User) &&
        !string.IsNullOrWhiteSpace(Password);

    [SkippableFact]
    public async Task Export_TracesMetricsLogs_VisibleInOpenObserve()
    {
        // Plan: skip only when OPENOBSERVE_* unset — not a silent green pass.
        Skip.IfNot(HasEnv, "OPENOBSERVE_URL/USER/PASSWORD not set");

        Testing.ResetForTests();
        var runId = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds().ToString();
        var baseUrl = Url!.TrimEnd('/');
        var auth = Convert.ToBase64String(Encoding.UTF8.GetBytes($"{User}:{Password}"));
        var headers = $"Authorization=Basic {auth}";

        Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", baseUrl);
        Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_HEADERS", headers);
        Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf");
        Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", "csharp-openobserve");
        Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_ENV", "integration");
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");
        Environment.SetEnvironmentVariable("PROVIDE_LOG_OTLP_ENDPOINT", baseUrl);
        Environment.SetEnvironmentVariable("PROVIDE_TRACE_OTLP_ENDPOINT", baseUrl);
        Environment.SetEnvironmentVariable("PROVIDE_METRICS_OTLP_ENDPOINT", baseUrl);
        Environment.SetEnvironmentVariable("PROVIDE_LOG_OTLP_HEADERS", headers);
        Environment.SetEnvironmentVariable("PROVIDE_TRACE_OTLP_HEADERS", headers);
        Environment.SetEnvironmentVariable("PROVIDE_METRICS_OTLP_HEADERS", headers);

        try
        {
            var cfg = ProvideTelemetry.SetupTelemetry();
            Assert.Equal("csharp-openobserve", cfg.ServiceName);

            var status = ProvideTelemetry.GetRuntimeStatus();
            Assert.True(status.Providers.Traces, "traces provider must be installed when OTLP endpoint set");
            Assert.True(status.Providers.Metrics, "metrics provider must be installed when OTLP endpoint set");
            Assert.True(status.Providers.Logs, "logs provider must be installed when OTLP endpoint set");

            var spanName = $"csharp.oo.span.{runId}";
            var metricName = $"csharp_oo_metric_{runId}";
            var logEvent = $"csharp.oo.log.{runId}";

            // Baseline counts (e2e pattern): search type=traces stream "default" by operation_name
            using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(20) };
            http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Basic", auth);

            var startUs = DateTimeOffset.UtcNow.AddHours(-2).ToUnixTimeMilliseconds() * 1000;
            var beforeTraces = await SearchTotalAsync(
                http, baseUrl, "traces",
                $"select * from \\\"default\\\" where operation_name = '{spanName}'",
                startUs, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() * 1000);

            using (var span = ProvideTelemetry.GetTracer("oo").StartSpan(spanName))
            {
                span.SetAttribute("run_id", runId);
                ProvideTelemetry.GetLogger("oo").Info(logEvent, new Dictionary<string, object?>
                {
                    ["run_id"] = runId,
                    ["event"] = logEvent,
                });
            }

            var counter = ProvideTelemetry.Counter(metricName);
            counter.Add(1, new Dictionary<string, object?> { ["run_id"] = runId });
            Assert.Equal(1, counter.Value);

            var flush = ProvideTelemetry.FlushTelemetry(TimeSpan.FromSeconds(15));
            Assert.True(flush.Traces.Flushed, $"traces flush failed: timedOut={flush.Traces.TimedOut} failed={flush.Traces.Failed}");
            Assert.True(flush.Metrics.Flushed, $"metrics flush failed: timedOut={flush.Metrics.TimedOut} failed={flush.Metrics.Failed}");
            Assert.True(flush.Logs.Flushed, $"logs OTLP flush failed: timedOut={flush.Logs.TimedOut} failed={flush.Logs.Failed} ni={flush.Logs.NotInstalled}");

            // Metrics: OTel creates a stream named after the metric (dots → underscores on OO)
            var metricStream = metricName.Replace('.', '_');
            var streamsJson = await WaitForAsync(
                async () => await http.GetStringAsync(baseUrl + "/streams?type=metrics"),
                body => body.Contains(metricName, StringComparison.OrdinalIgnoreCase)
                        || body.Contains(metricStream, StringComparison.OrdinalIgnoreCase),
                attempts: 10,
                delayMs: 750);
            Assert.True(
                streamsJson.Contains(metricName, StringComparison.OrdinalIgnoreCase)
                || streamsJson.Contains(metricStream, StringComparison.OrdinalIgnoreCase),
                $"OpenObserve metric streams missing {metricName}. body={streamsJson[..Math.Min(400, streamsJson.Length)]}");

            // Logs: OTLP/HTTP → OO default log stream; body/message/event may hold identity
            var endUs = DateTimeOffset.UtcNow.AddMinutes(5).ToUnixTimeMilliseconds() * 1000;
            var logFound = await WaitUntilAsync(async () =>
            {
                var total = await SearchTotalAsync(
                    http, baseUrl, "logs",
                    $"select * from \\\"default\\\" where match_all('{logEvent}') OR match_all('{runId}')",
                    startUs, endUs);
                if (total > 0) return true;
                // Fallback: scan recent hits for identity
                var hits = await SearchHitsAsync(http, baseUrl, "logs", "default", startUs, endUs, size: 50);
                var blob = string.Join("\n", hits.Select(h => JsonSerializer.Serialize(h)));
                return blob.Contains(logEvent, StringComparison.Ordinal) || blob.Contains(runId, StringComparison.Ordinal);
            }, attempts: 12, delayMs: 750);
            Assert.True(logFound, $"OpenObserve log search missing OTLP-exported event {logEvent}");

            // Traces: e2e pattern — type=traces, stream "default", filter operation_name
            var tracesOk = await WaitUntilAsync(async () =>
            {
                var after = await SearchTotalAsync(
                    http, baseUrl, "traces",
                    $"select * from \\\"default\\\" where operation_name = '{spanName}'",
                    startUs, endUs);
                return after > beforeTraces;
            }, attempts: 12, delayMs: 750);
            Assert.True(
                tracesOk,
                $"OpenObserve traces search did not increase for operation_name='{spanName}' (before={beforeTraces})");
        }
        finally
        {
            ProvideTelemetry.ShutdownTelemetry();
            foreach (var k in new[]
                     {
                         "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_HEADERS", "OTEL_EXPORTER_OTLP_PROTOCOL",
                         "PROVIDE_TELEMETRY_SERVICE_NAME", "PROVIDE_TELEMETRY_ENV", "PROVIDE_LOG_FORMAT",
                         "PROVIDE_LOG_OTLP_ENDPOINT", "PROVIDE_TRACE_OTLP_ENDPOINT", "PROVIDE_METRICS_OTLP_ENDPOINT",
                         "PROVIDE_LOG_OTLP_HEADERS", "PROVIDE_TRACE_OTLP_HEADERS", "PROVIDE_METRICS_OTLP_HEADERS",
                     })
            {
                Environment.SetEnvironmentVariable(k, null);
            }
            Testing.ResetForTests();
        }
    }

    private static async Task<string> WaitForAsync(
        Func<Task<string>> fetch, Func<string, bool> ok, int attempts, int delayMs)
    {
        string last = "";
        for (var i = 0; i < attempts; i++)
        {
            try { last = await fetch(); }
            catch { last = ""; }
            if (ok(last)) return last;
            await Task.Delay(delayMs);
        }
        return last;
    }

    private static async Task<bool> WaitUntilAsync(Func<Task<bool>> pred, int attempts, int delayMs)
    {
        for (var i = 0; i < attempts; i++)
        {
            if (await pred()) return true;
            await Task.Delay(delayMs);
        }
        return false;
    }

    /// <summary>POST {base}/_search?type={streamType} — matches e2e/_search_total.</summary>
    private static async Task<int> SearchTotalAsync(
        HttpClient http, string baseUrl, string streamType, string sql, long startUs, long endUs)
    {
        var searchUrl = baseUrl.TrimEnd('/') + "/_search?type=" + streamType;
        var body =
            "{\"query\":{\"sql\":\"" + sql + "\",\"start_time\":" + startUs
            + ",\"end_time\":" + endUs + "}}";
        using var content = new StringContent(body, Encoding.UTF8, "application/json");
        try
        {
            var resp = await http.PostAsync(searchUrl, content);
            var text = await resp.Content.ReadAsStringAsync();
            if (!resp.IsSuccessStatusCode)
            {
                if (text.Contains("Search stream not found", StringComparison.Ordinal)) return 0;
                return 0;
            }
            using var doc = JsonDocument.Parse(text);
            if (doc.RootElement.TryGetProperty("total", out var total))
            {
                return total.ValueKind == JsonValueKind.Number ? total.GetInt32() : 0;
            }
        }
        catch
        {
            // ignore
        }
        return 0;
    }

    private static async Task<List<JsonElement>> SearchHitsAsync(
        HttpClient http, string baseUrl, string streamType, string stream, long startUs, long endUs, int size)
    {
        var searchUrl = baseUrl.TrimEnd('/') + "/_search?type=" + streamType;
        var sql = "SELECT * FROM \\\"" + stream + "\\\"";
        var body =
            "{\"query\":{\"sql\":\"" + sql + "\",\"start_time\":" + startUs
            + ",\"end_time\":" + endUs + ",\"from\":0,\"size\":" + size + "}}";
        using var content = new StringContent(body, Encoding.UTF8, "application/json");
        try
        {
            var resp = await http.PostAsync(searchUrl, content);
            var text = await resp.Content.ReadAsStringAsync();
            if (!resp.IsSuccessStatusCode) return new List<JsonElement>();
            using var doc = JsonDocument.Parse(text);
            if (doc.RootElement.TryGetProperty("hits", out var hits) && hits.ValueKind == JsonValueKind.Array)
            {
                return hits.EnumerateArray().Select(e => e.Clone()).ToList();
            }
        }
        catch
        {
            // ignore
        }
        return new List<JsonElement>();
    }
}
