// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// The pretty renderer's contract: severity-colored padded levels, dim
/// timestamps and keys, quoted escaped values — and not a single ANSI byte
/// when the sink is not a terminal, which is also what every redirected
/// consumer (CI logs, files, pipes) receives.
/// </summary>
[Collection("Telemetry")]
public class PrettyRendererTests : IDisposable
{
    public PrettyRendererTests()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "pretty");
        Environment.SetEnvironmentVariable("PROVIDE_LOG_INCLUDE_TIMESTAMP", "false");
        Testing.ResetForTests();
        ProvideTelemetry.SetupTelemetry();
    }

    public void Dispose()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", null);
        Environment.SetEnvironmentVariable("PROVIDE_LOG_INCLUDE_TIMESTAMP", null);
        Testing.ResetForTests();
    }

    private static (IReadOnlyDictionary<string, object?> Output, CanonicalLogRecord Record) BuildRecord(
        string level,
        IReadOnlyDictionary<string, object?>? payload = null,
        bool includeTimestamp = false)
    {
        var cfg = Setup.GetRuntimeConfig() ?? TelemetryConfig.Default();
        var record = CanonicalLogRecord.Create(
            DateTimeOffset.UtcNow, level, "order.create.ok", "fmt", cfg,
            "", "",
            payload ?? new Dictionary<string, object?>(StringComparer.Ordinal), null);
        return (record.ToWireEnvelope(includeTimestamp), record);
    }

    [Theory]
    [InlineData("INFO", "info", PrettyRenderer.AnsiGreen)]
    [InlineData("ERROR", "error", PrettyRenderer.AnsiRed)]
    [InlineData("CRITICAL", "critical", PrettyRenderer.AnsiBoldRed)]
    [InlineData("WARNING", "warning", PrettyRenderer.AnsiYellow)]
    [InlineData("WARN", "warn", PrettyRenderer.AnsiYellow)]
    [InlineData("DEBUG", "debug", PrettyRenderer.AnsiBlue)]
    [InlineData("TRACE", "trace", PrettyRenderer.AnsiCyan)]
    public void EachLevelGetsItsSeverityColorLowercasedAndPadded(
        string level, string lower, string color)
    {
        var (output, record) = BuildRecord(level);

        var line = PrettyRenderer.Render(output, record, colors: true);

        var padded = lower.PadRight(PrettyRenderer.LevelPad);
        Assert.Contains($"[{color}{padded}{PrettyRenderer.AnsiReset}]", line);
    }

    [Fact]
    public void FatalMapsToBoldRedLikeCritical()
    {
        Assert.Equal(PrettyRenderer.AnsiBoldRed, PrettyRenderer.LevelColor("fatal"));
    }

    [Fact]
    public void AnUnknownLevelIsPaddedButUncolored()
    {
        var (output, record) = BuildRecord("NOTICE");

        var line = PrettyRenderer.Render(output, record, colors: true);

        Assert.Contains("[notice   ]", line);
    }

    [Fact]
    public void ColorlessRenderCarriesNoAnsiAndKeepsTheQuotedShape()
    {
        var (output, record) = BuildRecord(
            "INFO", new Dictionary<string, object?>(StringComparer.Ordinal) { ["count"] = 3 });

        var line = PrettyRenderer.Render(output, record, colors: false);

        Assert.DoesNotContain('\x1b', line);
        Assert.StartsWith("[info     ] order.create.ok ", line);
        Assert.Contains("count=\"3\"", line);
    }

    [Fact]
    public void KeysAreDimAndValuesStayUnwrapped()
    {
        var (output, record) = BuildRecord(
            "INFO", new Dictionary<string, object?>(StringComparer.Ordinal) { ["count"] = 3 });

        var line = PrettyRenderer.Render(output, record, colors: true);

        Assert.Contains(
            $"{PrettyRenderer.AnsiDim}count{PrettyRenderer.AnsiReset}=\"3\"", line);
    }

    [Fact]
    public void TheTimestampIsDimmedWhenColorsAreOn()
    {
        var (output, record) = BuildRecord("INFO", includeTimestamp: true);
        var ts = Assert.IsType<string>(output["timestamp"]);

        var line = PrettyRenderer.Render(output, record, colors: true);

        Assert.StartsWith($"{PrettyRenderer.AnsiDim}{ts}{PrettyRenderer.AnsiReset} [", line);
    }

    [Fact]
    public void ControlCharactersAreEscapedBeforeAnyColoringApplies()
    {
        var (output, record) = BuildRecord(
            "INFO", new Dictionary<string, object?>(StringComparer.Ordinal) { ["m"] = "l1\nl2" });

        var line = PrettyRenderer.Render(output, record, colors: true);

        Assert.DoesNotContain('\n', line);
        Assert.Contains($"m{PrettyRenderer.AnsiReset}=\"l1\\nl2\"", line);
    }

    [Fact]
    public void EmissionThroughARedirectedStderrIsColorless()
    {
        // dotnet's test host pipes the process stderr handle, so the
        // TTY autodetect must resolve to plain output here — an ANSI byte in
        // this capture means colors leaked into redirected consumers.
        var writer = new StringWriter();
        var original = Console.Error;
        Console.SetError(writer);
        try
        {
            ProvideTelemetry.GetLogger("fmt").Info(
                "order.create.ok", new Dictionary<string, object?> { ["count"] = 3 });
        }
        finally
        {
            Console.SetError(original);
        }
        var raw = writer.ToString();

        Assert.True(Console.IsErrorRedirected, "test needs a redirected stderr");
        Assert.DoesNotContain('\x1b', raw);
        Assert.StartsWith("[info     ] order.create.ok ", raw);
        Assert.Contains("count=\"3\"", raw);
    }
}
