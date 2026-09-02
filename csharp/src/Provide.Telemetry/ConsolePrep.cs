// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Diagnostics.CodeAnalysis;
using System.Runtime.InteropServices;
using System.Text;

namespace Provide.Telemetry;

/// <summary>
/// Readies a Windows console for what this SDK writes, and puts it back.
/// </summary>
/// <remarks>
/// <para>
/// A console is not a byte sink: it decodes what it is given with its output
/// code page, which is CP437 or CP1252 on a default console rather than UTF-8.
/// .NET encodes <see cref="Console.Error"/> with <see cref="Console.OutputEncoding"/>,
/// which defaults to that code page, so every non-ASCII character this SDK
/// wrote arrived mangled — an emoji a host uses to tell two runtimes apart in
/// one stream most visibly.
/// </para>
/// <para>
/// ANSI is the second half. <see cref="Console.IsErrorRedirected"/> is false for
/// a console, so colour switched on for every one of them — including legacy
/// conhost, which renders <c>ESC[36m</c> literally because
/// <c>ENABLE_VIRTUAL_TERMINAL_PROCESSING</c> is not set on it. The platform
/// least able to render ANSI was the one that got it unasked.
/// </para>
/// <para>
/// Both are restored at shutdown, and nothing is touched when stderr is
/// redirected: a file or a pipe receives exactly the bytes it received before.
/// See <c>windows_console</c> in <c>spec/telemetry-api.yaml</c>.
/// </para>
/// </remarks>
internal static class ConsolePrep
{
    private const int StdErrorHandle = -12;
    private const uint EnableVirtualTerminalProcessing = 0x0004;
    private const int CodePageUtf8 = 65001;

    private static readonly object Gate = new();
    private static Action? _restore;
    private static bool _vtEnabled;

    /// <summary>
    /// The three things this class cannot do on the machine that tests it.
    /// </summary>
    /// <remarks>
    /// Seams in the shape <c>Resilience.Clock</c> already uses. The interop
    /// itself only runs on Windows, and the coverage and mutation runs are
    /// Linux — without these the decisions around it would be unreachable
    /// there, which is the same silence that let the defect ship. Substituting
    /// them lets every branch be taken on any platform, leaving only the two
    /// P/Invoke bodies excluded.
    /// </remarks>
    internal static Func<bool> IsWindows { get; set; } = OperatingSystem.IsWindows;

    internal static Func<bool> IsErrorRedirected { get; set; } = () => Console.IsErrorRedirected;

    /// <summary>
    /// Prepares the console, reporting whether ANSI renders and how to undo it.
    /// A null restore means there was no console to prepare.
    /// </summary>
    internal static Func<(bool Ansi, Action? Restore)> PrepareConsole { get; set; } = PrepareWindowsConsole;

    /// <summary>Whether the destination renders ANSI escapes.</summary>
    /// <remarks>
    /// Away from Windows a terminal renders escapes without being asked, so a
    /// renderer built before <see cref="Prepare"/> runs is coloured exactly as
    /// it always was. On Windows it is the result of enabling virtual-terminal
    /// processing, and nothing else.
    /// </remarks>
    internal static bool AnsiEnabled
    {
        get
        {
            lock (Gate) return !IsWindows() || _vtEnabled;
        }
    }

    /// <summary>Ready the console. Idempotent while a preparation is in place.</summary>
    internal static void Prepare()
    {
        lock (Gate)
        {
            // A second preparation would overwrite the saved settings with the
            // ones this SDK installed, leaving the host's console on UTF-8 for
            // good. Every path that rebuilds runtime state calls this.
            if (_restore is not null) return;
            if (!IsWindows() || IsErrorRedirected()) return;
            (_vtEnabled, _restore) = PrepareConsole();
        }
    }

    /// <summary>Put back whatever <see cref="Prepare"/> changed.</summary>
    internal static void Restore()
    {
        lock (Gate)
        {
            _restore?.Invoke();
            _restore = null;
            _vtEnabled = false;
        }
    }

    /// <summary>Return the seams to their real implementations.</summary>
    internal static void ResetForTests()
    {
        Restore();
        IsWindows = OperatingSystem.IsWindows;
        IsErrorRedirected = () => Console.IsErrorRedirected;
        PrepareConsole = PrepareWindowsConsole;
    }

    /// <remarks>
    /// Excluded from coverage rather than left to drag the gate down: every
    /// line is a P/Invoke or a <see cref="Console"/> property that exists only
    /// on Windows, and the coverage run is Linux. Everything that decides
    /// whether this is called, and what its answer means, is above and is
    /// covered there with this replaced. The calls themselves are asserted
    /// against a real console screen buffer by the Go suite, which is the one
    /// place in this repository that can allocate one.
    /// </remarks>
    /// <remarks>
    /// Not marked SupportedOSPlatform("windows"): the seam above holds it as a
    /// default value, which CA1416 reads as a call site reachable everywhere.
    /// Prepare is what keeps it off other platforms, and that is tested.
    /// </remarks>
    [ExcludeFromCodeCoverage]
    private static (bool, Action?) PrepareWindowsConsole()
    {
        var handle = GetStdHandle(StdErrorHandle);
        var undo = new List<Action>(2);
        var ansi = false;

        if (GetConsoleMode(handle, out var mode))
        {
            ansi = (mode & EnableVirtualTerminalProcessing) != 0;
            if (!ansi && SetConsoleMode(handle, mode | EnableVirtualTerminalProcessing))
            {
                ansi = true;
                undo.Add(() => SetConsoleMode(handle, mode));
            }
        }

        try
        {
            if (Console.OutputEncoding.CodePage != CodePageUtf8)
            {
                var previous = Console.OutputEncoding;
                // No BOM: the encoding is applied per write, and a preamble
                // would put one at the head of a log line.
                Console.OutputEncoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);
                undo.Add(() => RestoreEncoding(previous));
            }
        }
        catch (IOException)
        {
            // No console attached after all. Leave the encoding alone.
        }

        if (undo.Count == 0) return (ansi, null);
        return (ansi, () =>
        {
            foreach (var step in undo) step();
        });
    }

    /// <remarks>Excluded for the same reason as <see cref="PrepareWindowsConsole"/>.</remarks>
    [ExcludeFromCodeCoverage]
    private static void RestoreEncoding(Encoding previous)
    {
        try
        {
            Console.OutputEncoding = previous;
        }
        catch (IOException)
        {
            // The console went away between setup and shutdown; there is
            // nothing left to restore it to.
        }
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr GetStdHandle(int nStdHandle);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetConsoleMode(IntPtr hConsoleHandle, out uint lpMode);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetConsoleMode(IntPtr hConsoleHandle, uint dwMode);
}
