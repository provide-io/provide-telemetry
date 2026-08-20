// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

// Transcribes the log_levels section of spec/behavioral_fixtures.yaml.
// The canonical ladder, the alias table, and the unrecognised-token fallback
// are cross-language contracts, not C# choices -- every port asserts these
// same vectors.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

[Collection("Telemetry")]
public class ParityLogLevelsTests
{
    public ParityLogLevelsTests() => Testing.ResetForTests();

    // ── canonical ladder ─────────────────────────────────────────────────────

    [Theory]
    [InlineData(LogSeverity.Trace, 0, "TRACE")]
    [InlineData(LogSeverity.Debug, 1, "DEBUG")]
    [InlineData(LogSeverity.Info, 2, "INFO")]
    [InlineData(LogSeverity.Warn, 3, "WARN")]
    [InlineData(LogSeverity.Error, 4, "ERROR")]
    [InlineData(LogSeverity.Critical, 5, "CRITICAL")]
    public void Canonical_OrderAndName(LogSeverity severity, int order, string name)
    {
        Assert.Equal(order, (int)severity);
        Assert.Equal(name, Levels.Name(severity));
    }

    [Fact]
    public void Canonical_LadderHasExactlySixMembers() =>
        Assert.Equal(6, Enum.GetValues<LogSeverity>().Length);

    // ── parse vectors ────────────────────────────────────────────────────────

    [Theory]
    [InlineData("ERROR", LogSeverity.Error, true)]
    [InlineData("error", LogSeverity.Error, true)]
    [InlineData("CrItIcAl", LogSeverity.Critical, true)]
    [InlineData("  warn  ", LogSeverity.Warn, true)]
    [InlineData("warning", LogSeverity.Warn, true)]
    [InlineData("WARNING", LogSeverity.Warn, true)]
    [InlineData("FATAL", LogSeverity.Critical, true)]
    [InlineData("CRITICAL", LogSeverity.Critical, true)]
    [InlineData("TRACE", LogSeverity.Trace, true)]
    [InlineData("DEBUG", LogSeverity.Debug, true)]
    [InlineData("INFO", LogSeverity.Info, true)]
    [InlineData("warnn", LogSeverity.Info, false)]
    [InlineData("warns", LogSeverity.Info, false)]
    [InlineData("", LogSeverity.Info, false)]
    [InlineData("   ", LogSeverity.Info, false)]
    [InlineData(null, LogSeverity.Info, false)]
    public void TryParse_Vectors(string? input, LogSeverity expected, bool recognised)
    {
        Assert.Equal(recognised, Levels.TryParse(input, out var actual));
        Assert.Equal(expected, actual);
    }

    [Fact]
    public void Parse_UsesCallerFallbackForUnrecognised()
    {
        Assert.Equal(LogSeverity.Info, Levels.Parse("warnn"));
        Assert.Equal(LogSeverity.Error, Levels.Parse("warnn", LogSeverity.Error));
        // A recognised level must ignore the fallback entirely.
        Assert.Equal(LogSeverity.Debug, Levels.Parse("debug", LogSeverity.Error));
    }

    // ── ordering ─────────────────────────────────────────────────────────────

    [Fact]
    public void Ordering_CriticalOutranksError() =>
        Assert.True(Levels.Parse("CRITICAL") > Levels.Parse("ERROR"));

    [Fact]
    public void Ordering_WarningEqualsWarn() =>
        Assert.Equal(Levels.Parse("WARN"), Levels.Parse("WARNING"));

    [Fact]
    public void Ordering_FatalEqualsCritical() =>
        Assert.Equal(Levels.Parse("CRITICAL"), Levels.Parse("FATAL"));

    [Fact]
    public void Ordering_TraceIsTheFloor() =>
        Assert.True(Levels.Parse("TRACE") < Levels.Parse("DEBUG"));

    // ── Logger.Log: the level-parameterised door ─────────────────────────────

    private static string[] CaptureStderr(Action action)
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
        return writer.ToString()
            .Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
    }

    [Theory]
    [InlineData(LogSeverity.Trace, "TRACE")]
    [InlineData(LogSeverity.Debug, "DEBUG")]
    [InlineData(LogSeverity.Info, "INFO")]
    [InlineData(LogSeverity.Warn, "WARN")]
    [InlineData(LogSeverity.Error, "ERROR")]
    [InlineData(LogSeverity.Critical, "CRITICAL")]
    public void Log_EmitsAtTheGivenLevel(LogSeverity severity, string rendered)
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_LEVEL", "TRACE");
        try
        {
            Testing.ResetForTests();
            var lines = CaptureStderr(() => Logging.GetLogger("lvl").Log(severity, "level.probe"));
            Assert.Single(lines);
            Assert.Contains($"[{rendered}]", lines[0]);
        }
        finally
        {
            Environment.SetEnvironmentVariable("PROVIDE_LOG_LEVEL", null);
            Testing.ResetForTests();
        }
    }

    [Fact]
    public void Log_IsGatedByTheConfiguredLevelLikeEveryOtherEntryPoint()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_LEVEL", "ERROR");
        try
        {
            Testing.ResetForTests();
            var logger = Logging.GetLogger("lvl");
            Assert.Empty(CaptureStderr(() => logger.Log(LogSeverity.Warn, "dropped")));
            Assert.Single(CaptureStderr(() => logger.Log(LogSeverity.Critical, "kept")));
        }
        finally
        {
            Environment.SetEnvironmentVariable("PROVIDE_LOG_LEVEL", null);
            Testing.ResetForTests();
        }
    }

    [Fact]
    public void Log_CollapsesTheDownstreamAdapterDispatchChain()
    {
        // The motivating case, from provide-uterm's ServerFactory: a component
        // reports (level, message) so it need not depend on a logger, and every
        // adapter re-implemented an if/else chain whose arms only ran when that
        // severity actually occurred -- leaving two of four permanently
        // uncovered. The whole chain is now one expression.
        Environment.SetEnvironmentVariable("PROVIDE_LOG_LEVEL", "TRACE");
        try
        {
            Testing.ResetForTests();
            var log = Logging.GetLogger("adapter");
            Action<string, string> onLog = (level, message) => log.Log(Levels.Parse(level), message);

            var lines = CaptureStderr(() =>
            {
                onLog("debug", "a");
                onLog("warn", "b");
                onLog("warning", "c");
                onLog("error", "d");
                onLog("fatal", "e");
                onLog("nonsense", "f");
            });

            Assert.Equal(6, lines.Length);
            Assert.Contains("[DEBUG]", lines[0]);
            Assert.Contains("[WARN]", lines[1]);
            // "warning" and "warn" land on the same rendered level -- exactly what
            // the old chain did when it mapped both onto log.Warn(message).
            Assert.Contains("[WARN]", lines[2]);
            Assert.Contains("[ERROR]", lines[3]);
            Assert.Contains("[CRITICAL]", lines[4]);
            // The chain's else-branch behaviour: an unrecognised level is INFO.
            Assert.Contains("[INFO]", lines[5]);
        }
        finally
        {
            Environment.SetEnvironmentVariable("PROVIDE_LOG_LEVEL", null);
            Testing.ResetForTests();
        }
    }
}
