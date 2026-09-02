// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Runtime.CompilerServices;
using System.Text.Json;

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// Where a record says it came from: the <c>filename</c> and <c>lineno</c>
/// fields gated by <c>PROVIDE_LOG_INCLUDE_CALLER</c>.
/// </summary>
/// <remarks>
/// Every expected line number is taken from a marker on the line above the call
/// rather than written as a literal, so the expectation moves with the file
/// instead of rotting the first time anything above it is edited. Asserting
/// merely that <em>some</em> lineno is present would pass against a logger
/// reporting its own frame, which is the drift the spec names explicitly.
/// </remarks>
[Collection("Telemetry")]
public class LoggerCallsiteTests : IDisposable
{
    private static readonly string[] TouchedVariables =
    {
        "PROVIDE_LOG_FORMAT", "PROVIDE_LOG_LEVEL", "PROVIDE_LOG_INCLUDE_CALLER",
        "PROVIDE_LOG_INCLUDE_TIMESTAMP", "PROVIDE_LOG_SANITIZE",
    };

    /// <summary>This file's own base name, as a record must spell it.</summary>
    private const string ThisFile = "LoggerCallsiteTests.cs";

    public LoggerCallsiteTests()
    {
        ClearEnvironment();
        Testing.ResetForTests();
    }

    public void Dispose()
    {
        ClearEnvironment();
        Testing.ResetForTests();
        GC.SuppressFinalize(this);
    }

    private static void ClearEnvironment()
    {
        foreach (var key in TouchedVariables) Environment.SetEnvironmentVariable(key, null);
    }

    /// <summary>The line this call appears on.</summary>
    private static int Line([CallerLineNumber] int line = 0) => line;

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

    /// <summary>Start a JSON runtime and return the single record the action emits.</summary>
    private static Dictionary<string, JsonElement> CaptureJson(Action action)
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");
        Environment.SetEnvironmentVariable("PROVIDE_LOG_LEVEL", "TRACE");
        Testing.ResetForTests();
        ProvideTelemetry.SetupTelemetry();
        var line = Assert.Single(CaptureStderr(action));
        return JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(line)!;
    }

    // ── the canonical contract ───────────────────────────────────────────────

    [Fact]
    public void TheRecordCarriesTheCallersOwnFileAndLine()
    {
        var logger = ProvideTelemetry.GetLogger("callsite");

        var expected = Line() + 1;
        var record = CaptureJson(() => logger.Info("callsite.record.ok"));

        Assert.Equal(ThisFile, record["filename"].GetString());
        Assert.Equal(expected, record["lineno"].GetInt32());
    }

    [Fact]
    public void TwoCallsOnDifferentLinesReportDifferentLineNumbers()
    {
        var logger = ProvideTelemetry.GetLogger("callsite");

        var firstLine = Line() + 1;
        var first = CaptureJson(() => logger.Info("callsite.first.ok"));
        var secondLine = Line() + 1;
        var second = CaptureJson(() => logger.Info("callsite.second.ok"));

        Assert.Equal(firstLine, first["lineno"].GetInt32());
        Assert.Equal(secondLine, second["lineno"].GetInt32());
        Assert.NotEqual(first["lineno"].GetInt32(), second["lineno"].GetInt32());
    }

    [Fact]
    public void TheLineNumberIsAJsonNumberRatherThanAStringifiedOne()
    {
        var logger = ProvideTelemetry.GetLogger("callsite");

        var record = CaptureJson(() => logger.Info("callsite.type.ok"));

        Assert.Equal(JsonValueKind.Number, record["lineno"].ValueKind);
    }

    [Fact]
    public void TheFilenameIsABaseNameAndNeverABuildMachinePath()
    {
        var logger = ProvideTelemetry.GetLogger("callsite");

        var record = CaptureJson(() => logger.Info("callsite.basename.ok"));

        var filename = record["filename"].GetString()!;
        Assert.DoesNotContain('/', filename);
        Assert.DoesNotContain('\\', filename);
        Assert.Equal(ThisFile, filename);
    }

    [Fact]
    public void TheReportedFrameIsTheCallersNotTheSdksOwn()
    {
        var logger = ProvideTelemetry.GetLogger("callsite");

        var record = CaptureJson(() => logger.Info("callsite.frame.ok"));

        Assert.NotEqual("Logger.cs", record["filename"].GetString());
        Assert.NotEqual("Signals.cs", record["filename"].GetString());
    }

    // ── the gate ─────────────────────────────────────────────────────────────

    [Fact]
    public void TheGateIsOnByDefaultSoAnUnconfiguredServiceGetsCallsites()
    {
        Assert.True(TelemetryConfig.Default().Logging.IncludeCaller);
        Assert.True(ConfigEnv.ConfigFromEnv().Logging.IncludeCaller);
    }

    [Fact]
    public void DisablingTheGateRemovesBothFieldsRatherThanBlankingThem()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_INCLUDE_CALLER", "false");
        var logger = ProvideTelemetry.GetLogger("callsite");

        var record = CaptureJson(() => logger.Info("callsite.disabled.ok"));

        Assert.False(record.ContainsKey("filename"));
        Assert.False(record.ContainsKey("lineno"));
    }

    [Fact]
    public void TheGateAlsoRemovesTheFieldsFromTheConsoleRenderer()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "console");
        Environment.SetEnvironmentVariable("PROVIDE_LOG_INCLUDE_TIMESTAMP", "false");
        Environment.SetEnvironmentVariable("PROVIDE_LOG_INCLUDE_CALLER", "false");
        Testing.ResetForTests();
        ProvideTelemetry.SetupTelemetry();

        var line = Assert.Single(CaptureStderr(
            () => ProvideTelemetry.GetLogger("callsite").Info("callsite.console.ok")));

        Assert.DoesNotContain("filename=", line, StringComparison.Ordinal);
        Assert.DoesNotContain("lineno=", line, StringComparison.Ordinal);
    }

    [Fact]
    public void TheConsoleRendererCarriesTheFieldsWhenTheGateIsOn()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "console");
        Environment.SetEnvironmentVariable("PROVIDE_LOG_INCLUDE_TIMESTAMP", "false");
        Testing.ResetForTests();
        ProvideTelemetry.SetupTelemetry();

        var expected = Line() + 1;
        var lines = CaptureStderr(() => ProvideTelemetry.GetLogger("callsite").Info("console.render.ok"));
        var line = Assert.Single(lines);

        Assert.Contains($"filename={ThisFile}", line, StringComparison.Ordinal);
        Assert.Contains($"lineno={expected}", line, StringComparison.Ordinal);
    }

    // ── every entry point ────────────────────────────────────────────────────

    [Fact]
    public void EveryLevelMethodReportsItsOwnCallSite()
    {
        var logger = ProvideTelemetry.GetLogger("callsite");
        // Marker and call share a line here, so each entry names its own.
        var emitters = new List<(string Level, int Line, Action Emit)>
        {
            ("TRACE", Line(), () => logger.Trace("callsite.level.ok")),
            ("DEBUG", Line(), () => logger.Debug("callsite.level.ok")),
            ("INFO", Line(), () => logger.Info("callsite.level.ok")),
            ("WARN", Line(), () => logger.Warn("callsite.level.ok")),
            ("WARNING", Line(), () => logger.Warning("callsite.level.ok")),
            ("ERROR", Line(), () => logger.Error("callsite.level.ok")),
            ("CRITICAL", Line(), () => logger.Critical("callsite.level.ok")),
        };

        foreach (var (level, expected, emit) in emitters)
        {
            var record = CaptureJson(emit);
            Assert.Equal(level, record["level"].GetString());
            Assert.Equal(ThisFile, record["filename"].GetString());
            Assert.Equal(expected, record["lineno"].GetInt32());
        }
    }

    [Fact]
    public void TheRuntimeLevelOverloadReportsTheCallSiteToo()
    {
        var logger = ProvideTelemetry.GetLogger("callsite");

        var expected = Line() + 1;
        var record = CaptureJson(() => logger.Log(LogSeverity.Warn, "callsite.dynamic.ok"));

        Assert.Equal(ThisFile, record["filename"].GetString());
        Assert.Equal(expected, record["lineno"].GetInt32());
    }

    [Fact]
    public void TheExceptionOverloadReportsTheCallSiteToo()
    {
        var logger = ProvideTelemetry.GetLogger("callsite");
        var boom = new InvalidOperationException("boom");

        var expected = Line() + 1;
        var record = CaptureJson(() => logger.Error("callsite.error.ok", boom));

        Assert.Equal(ThisFile, record["filename"].GetString());
        Assert.Equal(expected, record["lineno"].GetInt32());
        Assert.Equal(
            Fingerprint.ComputeErrorFingerprint(boom), record["error_fingerprint"].GetString());
    }

    // ── wrappers forward rather than lie ─────────────────────────────────────

    /// <summary>A consumer's own logging helper, passing the callsite through.</summary>
    private static void Audit(
        Logger logger,
        string message,
        [CallerFilePath] string file = "",
        [CallerLineNumber] int line = 0) =>
        logger.Info(message, null, file, line);

    [Fact]
    public void AWrapperThatForwardsTheCallsiteBlamesItsOwnCaller()
    {
        var logger = ProvideTelemetry.GetLogger("callsite");

        var expected = Line() + 1;
        var record = CaptureJson(() => Audit(logger, "callsite.wrapper.ok"));

        Assert.Equal(ThisFile, record["filename"].GetString());
        Assert.Equal(expected, record["lineno"].GetInt32());
    }

    [Fact]
    public void AnExplicitlyEmptyPathLeavesBothFieldsOffRatherThanEmittingBlanks()
    {
        var logger = ProvideTelemetry.GetLogger("callsite");

        // An adapter with no source position of its own to hand on.
        var record = CaptureJson(() => logger.Info("callsite.empty.ok", null, "", 0));

        Assert.False(record.ContainsKey("filename"));
        Assert.False(record.ContainsKey("lineno"));
    }

    // ── interaction with the rest of the pipeline ────────────────────────────

    [Fact]
    public void TheCallsiteIsAttachedAfterRedactionSoItIsNeverItselfRedacted()
    {
        // Same reasoning as _schema_error: routed through the sanitizer, an
        // SDK-owned field would be treated as a caller field.
        Environment.SetEnvironmentVariable("PROVIDE_LOG_SANITIZE", "true");
        var logger = ProvideTelemetry.GetLogger("callsite");

        var record = CaptureJson(() => logger.Info("callsite.sanitize.ok"));

        Assert.Equal(ThisFile, record["filename"].GetString());
        Assert.NotEqual(Pii.Redacted, record["filename"].GetString());
    }

    [Fact]
    public void TheCallsiteOverwritesACallerFieldOfTheSameName()
    {
        // The record's own vocabulary wins, exactly as the identity fields do in
        // CanonicalLogRecord.Create: one record carrying two meanings of
        // "filename" is worse than losing the caller's.
        var logger = ProvideTelemetry.GetLogger("callsite");

        var expected = Line() + 1;
        var record = CaptureJson(() => logger.Info(
            "callsite.collision.ok",
            new Dictionary<string, object?> { ["filename"] = "upload.pdf", ["lineno"] = -1 }));

        Assert.Equal(ThisFile, record["filename"].GetString());
        Assert.Equal(expected, record["lineno"].GetInt32());
    }

    // ── the base-name reduction itself ───────────────────────────────────────

    [Theory]
    [InlineData("/home/runner/work/repo/csharp/src/App.cs", "App.cs")]
    [InlineData(@"C:\build\repo\csharp\src\App.cs", "App.cs")]
    [InlineData("/App.cs", "App.cs")]
    [InlineData("App.cs", "App.cs")]
    [InlineData("", "")]
    public void BaseNameStripsEitherPlatformsSeparators(string path, string expected)
    {
        // Both separators on both platforms: CallerFilePath is baked in at
        // compile time, so an assembly built on Windows and run on Linux still
        // has to be reduced — Path.GetFileName leaves the whole path there.
        Assert.Equal(expected, Logger.BaseName(path));
    }
}
