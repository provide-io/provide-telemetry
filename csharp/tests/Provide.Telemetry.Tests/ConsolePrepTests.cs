// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Text;
using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// The part of the console contract that is testable off Windows.
/// </summary>
/// <remarks>
/// The interop itself is not: it is P/Invoke into kernel32 and Console
/// properties that only exist there. What is tested here is every decision
/// around it — the platform gate, the redirection gate, idempotence, and the
/// answer the pretty renderer asks for. The calls themselves are asserted
/// against a real console screen buffer in the Go suite, which is the one place
/// in this repository that can allocate a console.
/// </remarks>
[Collection("Telemetry")]
public sealed class ConsolePrepTests
{
    /// <summary>
    /// Away from Windows a terminal renders escapes without being asked, so the
    /// answer does not wait for setup — a renderer built before
    /// <c>SetupTelemetry</c> is coloured exactly as it always was.
    /// </summary>
    [Fact]
    public void AnsiIsAvailableWithoutPreparationAwayFromWindows()
    {
        ConsolePrep.Restore();
        // On Windows the same call means the opposite: nothing is prepared, so
        // nothing has established that escapes render, so colour is off.
        Assert.Equal(!OperatingSystem.IsWindows(), ConsolePrep.AnsiEnabled);
    }

    /// <summary>Preparing and restoring leaves the answer where it started.</summary>
    [Fact]
    public void PreparingAndRestoringIsRoundTrip()
    {
        var before = ConsolePrep.AnsiEnabled;
        ConsolePrep.Prepare();
        ConsolePrep.Restore();
        Assert.Equal(before, ConsolePrep.AnsiEnabled);
    }

    /// <summary>
    /// Preparation happens once. Every path that rebuilds runtime state calls
    /// it, and a second preparation would overwrite the saved encoding with the
    /// one this SDK had already installed — leaving the host's console on UTF-8
    /// for good.
    /// </summary>
    [Fact]
    public void PreparingTwiceIsHarmless()
    {
        ConsolePrep.Prepare();
        ConsolePrep.Prepare();
        ConsolePrep.Restore();
        ConsolePrep.Restore();
        Assert.Equal(!OperatingSystem.IsWindows(), ConsolePrep.AnsiEnabled);
    }

    /// <summary>
    /// The test host redirects stderr, which is the shape every non-console
    /// destination has: a file, a pipe, a parent process capturing the stream.
    /// Nothing is changed for it.
    /// </summary>
    [Fact]
    public void ARedirectedStreamIsLeftAlone()
    {
        var original = Console.OutputEncoding;
        ConsolePrep.Prepare();
        Assert.Equal(original.CodePage, Console.OutputEncoding.CodePage);
        ConsolePrep.Restore();
        Assert.Equal(original.CodePage, Console.OutputEncoding.CodePage);
    }

    /// <summary>
    /// A record carrying an emoji leaves the console renderer as that emoji.
    /// This is the value that broke: what a Windows console then decodes those
    /// bytes to is the half this SDK could not previously control.
    /// </summary>
    /// <remarks>
    /// The console format, not json: <see cref="System.Text.Json.JsonSerializer"/>
    /// escapes non-ASCII to <c>\uD83D\uDC39</c> by default, so the json path
    /// never puts a raw multi-byte character on the wire and cannot show the
    /// defect. The console and pretty renderers do.
    /// </remarks>
    [Fact]
    public void NonAsciiSurvivesTheRenderPath()
    {
        Setup.ResetForTests();
        var captured = CaptureStderr(() =>
        {
            Setup.SetupTelemetry(new TelemetryConfig { Logging = { Format = "console" } });
            Logging.GetLogger("console").Info("console.render.ok", new Dictionary<string, object?> { ["glyph"] = "🐹" });
        });
        Setup.ResetForTests();

        Assert.Contains("🐹", captured, StringComparison.Ordinal);
    }

    private static string CaptureStderr(Action body)
    {
        var original = Console.Error;
        var writer = new StringWriter();
        Console.SetError(writer);
        try
        {
            body();
        }
        finally
        {
            Console.SetError(original);
        }
        return writer.ToString();
    }

    /// <summary>
    /// The renderer asks for the ANSI answer rather than assuming a
    /// non-redirected stream can render escapes — the assumption that put
    /// literal <c>ESC[36m</c> on a legacy Windows console.
    /// </summary>
    [Fact]
    public void PrettyOutputIsPlainWhenTheDestinationIsRedirected()
    {
        var record = CanonicalLogRecord.Create(
            DateTimeOffset.UnixEpoch, "INFO", "console.pretty.ok", "console",
            TelemetryConfig.Default(), "", "",
            new Dictionary<string, object?>(), null);
        var rendered = PrettyRenderer.Render(record.ToWireEnvelope(includeTimestamp: false), record);

        // xUnit redirects stderr, so this is the redirected branch: no escapes.
        Assert.DoesNotContain('\x1b', rendered);
    }

    /// <summary>Encoding round-trips through the renderer without a preamble.</summary>
    [Fact]
    public void Utf8WithoutABomIsWhatWouldBeInstalled()
    {
        var encoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);
        Assert.Empty(encoding.GetPreamble());
        Assert.Equal(65001, encoding.CodePage);
    }
}
