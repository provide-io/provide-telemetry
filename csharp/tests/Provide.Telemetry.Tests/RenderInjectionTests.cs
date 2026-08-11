// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// Console and pretty renderers are line-oriented: a control character that
/// survives into the output forges records (CR/LF), rewrites the operator's
/// terminal (ESC), or truncates the line for downstream tooling (NUL). These
/// tests feed attacker-shaped events, keys and values through the real logger
/// and assert the emitted stream stays exactly one clean physical record.
/// </summary>
[Collection("Telemetry")]
public class RenderInjectionTests : IDisposable
{
    public RenderInjectionTests()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "console");
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

    /// <summary>Raw stderr capture — no line splitting, so forged extra lines are visible.</summary>
    private static string CaptureRawStderr(Action action)
    {
        var writer = new StringWriter();
        var original = Console.Error;
        Console.SetError(writer);
        try
        {
            action();
        }
        finally
        {
            Console.SetError(original);
        }
        return writer.ToString();
    }

    private static void AssertSingleCleanLine(string raw)
    {
        var trimmed = raw.TrimEnd('\r', '\n');
        Assert.DoesNotContain('\n', trimmed);
        Assert.DoesNotContain('\r', trimmed);
        Assert.DoesNotContain('\x1b', trimmed);
        Assert.DoesNotContain('\0', trimmed);
    }

    [Fact]
    public void ANewlineInTheEventCannotForgeASecondRecord()
    {
        var raw = CaptureRawStderr(() => ProvideTelemetry.GetLogger("inj").Info(
            "before\n[INFO] forged.event"));

        AssertSingleCleanLine(raw);
        Assert.Contains("before\\n[INFO] forged.event", raw);
    }

    [Fact]
    public void ACarriageReturnInTheEventIsEscaped()
    {
        var raw = CaptureRawStderr(() => ProvideTelemetry.GetLogger("inj").Info("a\rb"));

        AssertSingleCleanLine(raw);
        Assert.Contains("a\\rb", raw);
    }

    [Fact]
    public void AControlCharacterInAKeyIsEscaped()
    {
        var raw = CaptureRawStderr(() => ProvideTelemetry.GetLogger("inj").Info(
            "op.run.ok", new Dictionary<string, object?> { ["k\rey"] = "v" }));

        AssertSingleCleanLine(raw);
        Assert.Contains("k\\rey=v", raw);
    }

    [Fact]
    public void AnAnsiEscapeInAScalarValueIsEscaped()
    {
        var raw = CaptureRawStderr(() => ProvideTelemetry.GetLogger("inj").Info(
            "op.run.ok", new Dictionary<string, object?> { ["color"] = "x\u001b[31mred" }));

        AssertSingleCleanLine(raw);
        Assert.Contains("color=x\\u001b[31mred", raw);
    }

    [Fact]
    public void ANulInANestedValueIsEscaped()
    {
        var raw = CaptureRawStderr(() => ProvideTelemetry.GetLogger("inj").Info(
            "op.run.ok", new Dictionary<string, object?>
            {
                ["outer"] = new Dictionary<string, object?> { ["inner"] = "a\0b" },
            }));

        AssertSingleCleanLine(raw);
    }

    [Fact]
    public void PrettyModeEscapesQuotesInsideQuotedValues()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "pretty");
        Testing.ResetForTests();
        ProvideTelemetry.SetupTelemetry();

        var raw = CaptureRawStderr(() => ProvideTelemetry.GetLogger("inj").Info(
            "op.run.ok", new Dictionary<string, object?> { ["q"] = "a\"b" }));

        AssertSingleCleanLine(raw);
        Assert.Contains("q=\"a\\\"b\"", raw);
    }

    [Fact]
    public void PrettyModeEscapesNewlinesInsideQuotedValues()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "pretty");
        Testing.ResetForTests();
        ProvideTelemetry.SetupTelemetry();

        var raw = CaptureRawStderr(() => ProvideTelemetry.GetLogger("inj").Info(
            "op.run.ok", new Dictionary<string, object?> { ["m"] = "l1\nl2" }));

        AssertSingleCleanLine(raw);
        Assert.Contains("m=\"l1\\nl2\"", raw);
    }

    [Fact]
    public void ConsoleModeDoesNotEscapeQuotes()
    {
        var raw = CaptureRawStderr(() => ProvideTelemetry.GetLogger("inj").Info(
            "op.run.ok", new Dictionary<string, object?> { ["q"] = "a\"b" }));

        Assert.Contains("q=a\"b", raw);
    }

    [Fact]
    public void ATabIsEscapedNotEmittedRaw()
    {
        var raw = CaptureRawStderr(() => ProvideTelemetry.GetLogger("inj").Info(
            "op.run.ok", new Dictionary<string, object?> { ["t"] = "a\tb" }));

        AssertSingleCleanLine(raw);
        Assert.Contains("t=a\\tb", raw);
        Assert.DoesNotContain("a\tb", raw);
    }

    [Fact]
    public void ADelCharacterIsEscaped()
    {
        // \u007f, not \x7f: C#'s \x escape is variable-length and would
        // swallow the following 'b' into U+07FB.
        var raw = CaptureRawStderr(() => ProvideTelemetry.GetLogger("inj").Info(
            "op.run.ok", new Dictionary<string, object?> { ["d"] = "a\u007fb" }));

        AssertSingleCleanLine(raw);
        Assert.DoesNotContain('\u007f', raw);
        Assert.Contains("d=a\\u007fb", raw);
    }

    [Fact]
    public void ACleanRecordIsRenderedByteForByteAsBefore()
    {
        var raw = CaptureRawStderr(() => ProvideTelemetry.GetLogger("fmt").Info(
            "order.create.ok", new Dictionary<string, object?> { ["count"] = 3 }));

        Assert.StartsWith("[INFO] order.create.ok ", raw);
        Assert.Contains("count=3", raw);
    }
}
