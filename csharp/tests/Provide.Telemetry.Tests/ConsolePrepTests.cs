// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Text;
using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// The console contract, driven from any platform.
/// </summary>
/// <remarks>
/// The interop itself is P/Invoke into kernel32 and Windows-only
/// <see cref="Console"/> properties, and is excluded from coverage. Everything
/// that decides whether it is called and what its answer means is substituted
/// here, so the Windows branches are taken on the Linux runner too — a gate
/// that cannot reach the platform-specific half is the silence that let this
/// ship. The calls themselves are asserted against a real console screen
/// buffer by the Go suite, which is the one place in this repository that can
/// allocate one.
/// </remarks>
[Collection("Telemetry")]
public sealed class ConsolePrepTests : IDisposable
{
    public void Dispose() => ConsolePrep.ResetForTests();

    /// <summary>Pretend to be a Windows console whose preparation succeeds.</summary>
    private static Func<int> OnWindows(bool ansi = true, bool redirected = false)
    {
        var restores = 0;
        ConsolePrep.IsWindows = () => true;
        ConsolePrep.IsErrorRedirected = () => redirected;
        ConsolePrep.PrepareConsole = () => (ansi, () => restores++);
        return () => restores;
    }

    // ── ANSI ─────────────────────────────────────────────────────────────

    [Fact]
    public void AnsiIsAvailableWithoutPreparationAwayFromWindows()
    {
        ConsolePrep.IsWindows = () => false;
        // No Prepare() call: away from Windows a terminal renders escapes
        // without being asked, so a renderer built before SetupTelemetry is
        // coloured exactly as it always was.
        Assert.True(ConsolePrep.AnsiEnabled);
    }

    [Fact]
    public void AnsiIsOffOnAnUnpreparedWindowsConsole()
    {
        ConsolePrep.IsWindows = () => true;
        Assert.False(ConsolePrep.AnsiEnabled);
    }

    [Fact]
    public void AnsiFollowsWhatPreparationReported()
    {
        OnWindows(ansi: true);
        ConsolePrep.Prepare();
        Assert.True(ConsolePrep.AnsiEnabled);
    }

    /// <summary>
    /// Legacy conhost refuses virtual-terminal processing and prints the escape
    /// literally. Reporting colour from "is a console" alone put escapes on the
    /// one platform least able to render them.
    /// </summary>
    [Fact]
    public void AnsiIsOffWhenVirtualTerminalProcessingCouldNotBeEnabled()
    {
        OnWindows(ansi: false);
        ConsolePrep.Prepare();
        Assert.False(ConsolePrep.AnsiEnabled);
    }

    // ── preparation ──────────────────────────────────────────────────────

    [Fact]
    public void PreparingAndRestoringIsRoundTrip()
    {
        var restores = OnWindows();
        ConsolePrep.Prepare();
        ConsolePrep.Restore();

        Assert.Equal(1, restores());
        Assert.False(ConsolePrep.AnsiEnabled);
    }

    /// <summary>
    /// A second preparation would overwrite the saved settings with the ones
    /// this SDK installed, leaving the host's console on UTF-8 for good. Every
    /// path that rebuilds runtime state calls Prepare.
    /// </summary>
    [Fact]
    public void PreparingTwicePreparesOnce()
    {
        var prepared = 0;
        ConsolePrep.IsWindows = () => true;
        ConsolePrep.IsErrorRedirected = () => false;
        ConsolePrep.PrepareConsole = () =>
        {
            prepared++;
            return (true, () => { });
        };

        ConsolePrep.Prepare();
        ConsolePrep.Prepare();

        Assert.Equal(1, prepared);
    }

    [Fact]
    public void RestoringTwiceRestoresOnce()
    {
        var restores = OnWindows();
        ConsolePrep.Prepare();
        ConsolePrep.Restore();
        ConsolePrep.Restore();

        Assert.Equal(1, restores());
    }

    [Fact]
    public void RestoringWithoutPreparingIsHarmless()
    {
        ConsolePrep.Restore();
        ConsolePrep.IsWindows = () => false;
        Assert.True(ConsolePrep.AnsiEnabled);
    }

    /// <summary>
    /// No console found means nothing to undo, and the next setup gets its own
    /// chance rather than being told a preparation is already in place.
    /// </summary>
    [Fact]
    public void APreparationThatFoundNoConsoleIsRetried()
    {
        var attempts = 0;
        ConsolePrep.IsWindows = () => true;
        ConsolePrep.IsErrorRedirected = () => false;
        ConsolePrep.PrepareConsole = () =>
        {
            attempts++;
            return (false, null);
        };

        ConsolePrep.Prepare();
        ConsolePrep.Prepare();

        Assert.Equal(2, attempts);
    }

    /// <summary>
    /// A redirected stream is every non-console destination: a file, a pipe, a
    /// parent process capturing the stream. Nothing is changed for it.
    /// </summary>
    [Fact]
    public void ARedirectedStreamIsNeverPrepared()
    {
        ConsolePrep.IsWindows = () => true;
        ConsolePrep.IsErrorRedirected = () => true;
        ConsolePrep.PrepareConsole = () => throw new InvalidOperationException("prepared a redirected stream");

        ConsolePrep.Prepare();

        Assert.False(ConsolePrep.AnsiEnabled);
    }

    [Fact]
    public void NothingIsPreparedAwayFromWindows()
    {
        ConsolePrep.IsWindows = () => false;
        ConsolePrep.IsErrorRedirected = () => false;
        ConsolePrep.PrepareConsole = () => throw new InvalidOperationException("prepared a console off Windows");

        ConsolePrep.Prepare();

        Assert.True(ConsolePrep.AnsiEnabled);
    }

    // ── what actually reaches the stream ─────────────────────────────────

    /// <summary>
    /// A record carrying an emoji leaves the renderer as that emoji. This is
    /// the value that broke; what a Windows console then decodes those bytes to
    /// is the half this SDK could not previously control.
    /// </summary>
    /// <remarks>
    /// The console format, not json: <see cref="System.Text.Json.JsonSerializer"/>
    /// escapes non-ASCII by default, so the json path never puts a raw
    /// multi-byte character on the wire and cannot show the defect.
    /// </remarks>
    [Fact]
    public void NonAsciiSurvivesTheRenderPath()
    {
        Setup.ResetForTests();
        var captured = CaptureStderr(() =>
        {
            Setup.SetupTelemetry(new TelemetryConfig { Logging = { Format = "console" } });
            Logging.GetLogger("console").Info(
                "console.render.ok", new Dictionary<string, object?> { ["glyph"] = "🐹" });
        });
        Setup.ResetForTests();

        Assert.Contains("🐹", captured, StringComparison.Ordinal);
    }

    /// <summary>
    /// The renderer asks for the ANSI answer rather than assuming a
    /// non-redirected stream can render escapes.
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

    /// <summary>The encoding that would be installed carries no preamble.</summary>
    [Fact]
    public void Utf8WithoutABomIsWhatWouldBeInstalled()
    {
        var encoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);
        Assert.Empty(encoding.GetPreamble());
        Assert.Equal(65001, encoding.CodePage);
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
}
