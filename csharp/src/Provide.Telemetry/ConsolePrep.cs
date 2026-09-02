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
    private static Encoding? _previousEncoding;
    private static uint? _previousMode;
    private static bool _vtEnabled;

    /// <summary>
    /// Whether the destination renders ANSI escapes.
    /// </summary>
    /// <remarks>
    /// Always true away from Windows, where a terminal renders escapes without
    /// being asked — so a renderer built before <see cref="Prepare"/> runs is
    /// coloured exactly as it always was. On Windows it is the result of
    /// enabling virtual-terminal processing, and nothing else.
    /// </remarks>
    internal static bool AnsiEnabled
    {
        get
        {
            if (!OperatingSystem.IsWindows()) return true;
            lock (Gate) return _vtEnabled;
        }
    }

    /// <summary>Ready the console. Idempotent; a second call does nothing.</summary>
    internal static void Prepare()
    {
        if (!OperatingSystem.IsWindows()) return;
        lock (Gate)
        {
            if (_previousEncoding is not null || _previousMode is not null || _vtEnabled) return;
            if (Console.IsErrorRedirected) return;
            PrepareWindowsConsole();
        }
    }

    /// <summary>Put back whatever <see cref="Prepare"/> changed.</summary>
    internal static void Restore()
    {
        if (!OperatingSystem.IsWindows()) return;
        lock (Gate)
        {
            RestoreWindowsConsole();
            _previousEncoding = null;
            _previousMode = null;
            _vtEnabled = false;
        }
    }

    /// <remarks>
    /// Excluded from coverage rather than left to drag the gate down: every
    /// line is a P/Invoke or a Console property that only exists on Windows,
    /// and the coverage run is Linux. What is testable — the platform gate, the
    /// redirection gate, idempotence and the ANSI answer — is above this and is
    /// covered there. The behaviour of the calls themselves is asserted by the
    /// Go suite against a real console screen buffer, which is the only place
    /// in this repository that can allocate one.
    /// </remarks>
    [ExcludeFromCodeCoverage]
    [System.Runtime.Versioning.SupportedOSPlatform("windows")]
    private static void PrepareWindowsConsole()
    {
        var handle = GetStdHandle(StdErrorHandle);
        if (GetConsoleMode(handle, out var mode))
        {
            _vtEnabled = (mode & EnableVirtualTerminalProcessing) != 0;
            if (!_vtEnabled && SetConsoleMode(handle, mode | EnableVirtualTerminalProcessing))
            {
                _vtEnabled = true;
                _previousMode = mode;
            }
        }

        try
        {
            if (Console.OutputEncoding.CodePage == CodePageUtf8) return;
            _previousEncoding = Console.OutputEncoding;
            // No BOM: the encoding is applied per write, and a preamble would
            // put one at the head of a log line.
            Console.OutputEncoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);
        }
        catch (IOException)
        {
            // No console attached after all. Leave the encoding alone.
            _previousEncoding = null;
        }
    }

    /// <remarks>Excluded for the same reason as <see cref="PrepareWindowsConsole"/>.</remarks>
    [ExcludeFromCodeCoverage]
    [System.Runtime.Versioning.SupportedOSPlatform("windows")]
    private static void RestoreWindowsConsole()
    {
        if (_previousMode is { } mode)
        {
            SetConsoleMode(GetStdHandle(StdErrorHandle), mode);
        }
        if (_previousEncoding is null) return;
        try
        {
            Console.OutputEncoding = _previousEncoding;
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
