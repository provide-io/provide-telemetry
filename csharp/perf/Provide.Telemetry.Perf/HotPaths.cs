// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

namespace Provide.Telemetry.Perf;

/// <summary>One measured hot path: a stable name and the body to time.</summary>
/// <param name="Name">
/// Key written to the JSON blob and looked up in <c>baselines/perf-csharp.json</c>.
/// Renaming one silently drops its budget (it reappears as a
/// <c>missing_baseline_entries</c> entry), so treat these as an interface.
/// </param>
/// <param name="IterationDivisor">
/// Divides the global iteration count. The expensive paths (a full log
/// emission, a span, a 50-key sanitize) are two to three orders of magnitude
/// slower than <c>ShouldSample</c>; running them the same number of times would
/// make a run take minutes to say the same thing.
/// </param>
/// <param name="Body">The operation under test. Must return a value the caller
/// can sink, so the JIT cannot delete the loop as dead code.</param>
internal sealed record HotPath(string Name, int IterationDivisor, Func<object?> Body);

/// <summary>
/// The hot paths the C# gate measures, chosen to match what the other four
/// SDK benchmarks already cover.
/// </summary>
/// <remarks>
/// Python (<c>scripts/run_performance_smoke.py</c>) and Go
/// (<c>go/benchmark_test.go</c>) measure event naming, sampling, sanitization,
/// metric instruments and the health snapshot; TypeScript
/// (<c>typescript/scripts/perf-smoke.ts</c>) adds log emission and a span;
/// Rust (<c>rust/benches/hot_path.rs</c>) adds W3C header extraction. This set
/// is the union, so a C# regression in any path another language guards is
/// caught here too.
/// </remarks>
internal static class HotPaths
{
    /// <summary>Signal name used for the per-signal policies. Mirrors the
    /// SDK-internal <c>Signals.Logs</c>, which is not public.</summary>
    private const string LogsSignal = "logs";

    /// <summary>Depth passed to the sanitizer — the SDK's own default.</summary>
    private const int SanitizeMaxDepth = 8;

    /// <summary>Prepare process-wide state so every measurement times the
    /// steady-state path rather than a first-call initialisation.</summary>
    internal static void Prepare()
    {
        Testing.ResetForTests();
        ProvideTelemetry.SetupTelemetry(new TelemetryConfig
        {
            ServiceName = "perf-smoke",
            Environment = "bench",
            Version = "0.0.0",
            // JSON is the production rendering path; "console" exists for
            // humans at a terminal and is not what a service pays for.
            Logging = { Format = "json", Level = "INFO" },
        });
        // Explicit rather than inherited from the environment: a stray
        // PROVIDE_* variable in the operator's shell would otherwise silently
        // change what "the sampling hot path" means between two runs.
        ProvideTelemetry.SetSamplingPolicy(LogsSignal, new SamplingPolicy { DefaultRate = 1.0 });
        ProvideTelemetry.SetQueuePolicy(new QueuePolicy()); // 0 == unlimited
    }

    internal static IReadOnlyList<HotPath> Build()
    {
        var smallPayload = new Dictionary<string, object?>(StringComparer.Ordinal)
        {
            ["password"] = "secret", // pragma: allowlist secret
            ["token"] = "abc",
            ["request_id"] = "r1",
        };

        var largePayload = new Dictionary<string, object?>(StringComparer.Ordinal);
        for (var i = 0; i < 50; i++)
        {
            largePayload[$"field_{i}"] = $"value_{i}";
        }
        largePayload["password"] = "secret"; // pragma: allowlist secret
        largePayload["token"] = "abc";

        var logFields = new Dictionary<string, object?>(StringComparer.Ordinal)
        {
            ["request_id"] = "r1",
            ["user_id"] = "u1",
        };

        var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["traceparent"] = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
            ["tracestate"] = "vendor=value",
            ["baggage"] = "region=us-east-1,tier=gold",
        };

        var logger = ProvideTelemetry.GetLogger("perf");
        var counter = ProvideTelemetry.Counter("perf.bench.counter");
        var gauge = ProvideTelemetry.Gauge("perf.bench.gauge");
        var histogram = ProvideTelemetry.Histogram("perf.bench.histogram");

        return
        [
            new HotPath("event_name_ns", 1, () => ProvideTelemetry.Event("auth", "login", "success")),
            new HotPath("should_sample_ns", 1, () => ProvideTelemetry.ShouldSample(LogsSignal, "auth.login.success")),
            new HotPath("sanitize_small_ns", 10, () => Pii.SanitizePayload(smallPayload, true, SanitizeMaxDepth)),
            new HotPath("sanitize_large_ns", 100, () => Pii.SanitizePayload(largePayload, true, SanitizeMaxDepth)),
            new HotPath("sanitize_disabled_ns", 10, () => Pii.SanitizePayload(smallPayload, false, SanitizeMaxDepth)),
            new HotPath("logger_info_ns", 100, () =>
            {
                logger.Info("perf.bench.log", logFields);
                return null;
            }),
            new HotPath("trace_span_ns", 20, () =>
            {
                ProvideTelemetry.Trace("perf.bench.span", static () => { });
                return null;
            }),
            new HotPath("counter_add_ns", 1, () =>
            {
                counter.Add(1);
                return null;
            }),
            new HotPath("gauge_set_ns", 1, () =>
            {
                gauge.Set(42.0);
                return null;
            }),
            new HotPath("histogram_record_ns", 1, () =>
            {
                histogram.Record(3.14);
                return null;
            }),
            new HotPath("health_snapshot_ns", 1, ProvideTelemetry.GetHealthSnapshot),
            new HotPath("extract_w3c_context_ns", 10, () => ProvideTelemetry.ExtractW3CContext(headers)),
            new HotPath("try_acquire_release_ns", 1, () =>
            {
                var ticket = Backpressure.TryAcquire(LogsSignal);
                Backpressure.Release(ticket);
                return null;
            }),
        ];
    }
}
