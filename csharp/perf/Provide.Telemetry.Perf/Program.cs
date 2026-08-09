// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Diagnostics;
using System.Globalization;
using System.Text.Json;

namespace Provide.Telemetry.Perf;

/// <summary>
/// Hot-path performance smoke runner for the C# SDK.
/// </summary>
/// <remarks>
/// Deliberately hand-rolled rather than BenchmarkDotNet: the four sibling SDKs
/// all feed <c>scripts/perf_check.py</c> a flat <c>{op_name: ns_per_op}</c>
/// blob from a plain timing loop, and the gate's 5x tolerance makes
/// BenchmarkDotNet's statistical machinery (and its extra process launches,
/// which would triple CI time) precision nobody consumes. Adding the dependency
/// would also break the house rule that the benchmark builds from the same
/// dependency set as the SDK.
/// </remarks>
internal static class Program
{
    /// <summary>Matches the Python runner's default; the Makefile target
    /// overrides it upward for the gate.</summary>
    private const int DefaultIterations = 200_000;

    /// <summary>Repeated runs whose median is reported, so one scheduler
    /// hiccup cannot decide the verdict.</summary>
    private const int DefaultRuns = 5;

    private const double NanosPerSecond = 1_000_000_000.0;

    /// <summary>
    /// Where every benchmark's return value lands.
    /// </summary>
    /// <remarks>
    /// Volatile and static so the JIT must treat each store as observable.
    /// Without it, RyuJIT is free to prove the loop body has no effect and
    /// delete it, and the gate would happily certify a 0.3ns "sanitize".
    /// </remarks>
    private static volatile object? _sink;

    private static int Main(string[] args)
    {
        var emitJson = args.Contains("--emit-json")
                       || string.Equals(
                           System.Environment.GetEnvironmentVariable("PERF_EMIT_JSON"),
                           "1",
                           StringComparison.Ordinal);
        var iterations = ParseIntOption(args, "--iterations", DefaultIterations);
        var runs = ParseIntOption(args, "--runs", DefaultRuns);

        // A Debug build measures unoptimised IL: the numbers are a different
        // quantity from the Release ones the baselines hold, and feeding them
        // to an unseeded bucket would enshrine garbage as the budget. MSBuild
        // defaults Configuration to Debug, so forgetting `-c Release` is one
        // keystroke away -- refuse rather than emit.
        if (emitJson && !IsOptimized())
        {
            Console.Error.WriteLine(
                "perf: refusing to emit measurements from an unoptimised build; rebuild with -c Release");
            return 2;
        }

        HotPaths.Prepare();
        var paths = HotPaths.Build();

        // The canonical logger writes rendered records to stderr. Left alone,
        // `logger_info_ns` would be a measurement of the terminal or the pipe
        // on the other end, not of the processor chain -- and on a redirected
        // stderr it would also bury the JSON blob under 2,000 log lines. The
        // record is still built, hardened, sanitized and rendered; only the
        // final write is discarded.
        var originalError = Console.Error;
        Console.SetError(TextWriter.Null);
        Dictionary<string, double> measurements;
        try
        {
            // Discarded warm-up. Tiered compilation is off (see the csproj), so
            // this is not about JIT tiers: it is the first-call costs the SDK
            // pays once -- static constructors, the regex caches behind secret
            // detection, dictionary and GC-heap growth -- which would otherwise
            // land entirely on the first measured run.
            Measure(paths, Math.Max(1, iterations / 20));
            measurements = MedianOf(paths, iterations, Math.Max(1, runs));
        }
        finally
        {
            Console.SetError(originalError);
        }

        if (emitJson)
        {
            // Flat {op_name: ns_per_op} blob -- consumed by scripts/perf_check.py.
            Console.WriteLine(JsonSerializer.Serialize(
                measurements.ToDictionary(kv => kv.Key, kv => Math.Round(kv.Value, 2))));
            return 0;
        }

        PrintTable(measurements, iterations, runs);
        return 0;
    }

    /// <summary>True when the JIT optimizer is enabled for this assembly.</summary>
    /// <remarks>
    /// Reads the attribute the compiler stamps rather than <c>#if DEBUG</c>, so
    /// a Release build that someone has turned <c>Optimize</c> off in is caught
    /// too -- the question is whether the code is optimised, not what the
    /// configuration is called.
    /// </remarks>
    private static bool IsOptimized()
    {
        var debuggable = typeof(Program).Assembly
            .GetCustomAttributes(typeof(DebuggableAttribute), inherit: false)
            .OfType<DebuggableAttribute>()
            .FirstOrDefault();
        return debuggable is null || !debuggable.IsJITOptimizerDisabled;
    }

    /// <summary>Run every hot path once and return ns/op for each.</summary>
    private static Dictionary<string, double> Measure(IReadOnlyList<HotPath> paths, int iterations)
    {
        var result = new Dictionary<string, double>(StringComparer.Ordinal);
        foreach (var path in paths)
        {
            var count = Math.Max(1, iterations / path.IterationDivisor);
            result[path.Name] = BenchNsPerOp(count, path.Body);
        }
        return result;
    }

    private static Dictionary<string, double> MedianOf(
        IReadOnlyList<HotPath> paths, int iterations, int runs)
    {
        var samples = new List<Dictionary<string, double>>(runs);
        for (var run = 0; run < runs; run++)
        {
            samples.Add(Measure(paths, iterations));
        }

        var median = new Dictionary<string, double>(StringComparer.Ordinal);
        foreach (var path in paths)
        {
            var values = samples.Select(sample => sample[path.Name]).Order().ToArray();
            // Even sample counts take the lower middle rather than the mean of
            // the two: averaging would let a single outlier drag the reported
            // number, which is the whole reason the median is here.
            median[path.Name] = values[(values.Length - 1) / 2];
        }
        return median;
    }

    private static double BenchNsPerOp(int iterations, Func<object?> body)
    {
        // Stopwatch, not DateTime: on Linux this is clock_gettime(MONOTONIC),
        // which is both immune to wall-clock adjustment and ~100x finer than
        // DateTime.UtcNow's tick granularity.
        var start = Stopwatch.GetTimestamp();
        for (var i = 0; i < iterations; i++)
        {
            _sink = body();
        }
        var ticks = Stopwatch.GetTimestamp() - start;
        return ticks * NanosPerSecond / Stopwatch.Frequency / iterations;
    }

    private static int ParseIntOption(string[] args, string name, int fallback)
    {
        for (var i = 0; i < args.Length - 1; i++)
        {
            if (string.Equals(args[i], name, StringComparison.Ordinal)
                && int.TryParse(args[i + 1], CultureInfo.InvariantCulture, out var parsed)
                && parsed > 0)
            {
                return parsed;
            }
        }
        return fallback;
    }

    private static void PrintTable(
        IReadOnlyDictionary<string, double> measurements, int iterations, int runs)
    {
        Console.WriteLine();
        Console.WriteLine(string.Create(
            CultureInfo.InvariantCulture,
            $"C# hot-path smoke -- {iterations} iterations, {runs} runs, median reported"));
        var width = measurements.Keys.Max(key => key.Length);
        foreach (var (name, nanos) in measurements.OrderBy(kv => kv.Key, StringComparer.Ordinal))
        {
            Console.WriteLine(string.Create(
                CultureInfo.InvariantCulture,
                $"  {name.PadRight(width)}  {nanos,12:F2} ns/op"));
        }
        Console.WriteLine();
    }
}
