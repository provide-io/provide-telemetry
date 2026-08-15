// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// Boundary pins for the renderer's escape class, the level rank table, the
/// module-override match, and the console renderer's reserved keys — each a
/// surviving mutant the emission suites exercised without asserting.
/// </summary>
[Collection("Telemetry")]
public class LoggerEscapeBoundaryTests : IDisposable
{
    public LoggerEscapeBoundaryTests()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "console");
        Environment.SetEnvironmentVariable("PROVIDE_LOG_INCLUDE_TIMESTAMP", "false");
        Testing.ResetForTests();
        ProvideTelemetry.SetupTelemetry();
    }

    public void Dispose()
    {
        foreach (var v in new[]
        {
            "PROVIDE_LOG_FORMAT", "PROVIDE_LOG_INCLUDE_TIMESTAMP", "PROVIDE_LOG_MODULE_LEVELS",
            "PROVIDE_LOG_LEVEL", "PROVIDE_TELEMETRY_SERVICE_NAME",
        })
        {
            Environment.SetEnvironmentVariable(v, null);
        }
        Testing.ResetForTests();
    }

    private static string CaptureStderr(Action action)
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

    [Theory]
    [InlineData(" ", false, " ")]
    [InlineData("\u001f", false, "\\u001f")]
    [InlineData("\u007f", false, "\\u007f")]
    [InlineData("\t", false, "\\t")]
    [InlineData("a\"b", false, "a\"b")]
    [InlineData("a\"b", true, "a\\\"b")]
    [InlineData("!~", false, "!~")]
    public void TheEscapeClassStopsExactlyAtSpaceDelAndConditionalQuotes(
        string input, bool escapeQuotes, string expected)
    {
        Assert.Equal(expected, Logger.EscapeControl(input, escapeQuotes));
    }

    [Fact]
    public void AnExactNameModuleOverrideBeatsTheGlobalLevel()
    {
        // The spec scopes PROVIDE_LOG_MODULE_LEVELS to the other four
        // languages; in C# module levels arrive only on the config object.
        Testing.ResetForTests();
        var cfg = TelemetryConfig.Default();
        cfg.Logging.ModuleLevels["a"] = "ERROR";
        ProvideTelemetry.SetupTelemetry(cfg);

        Assert.Equal("", CaptureStderr(() => ProvideTelemetry.GetLogger("a").Info("mod.gate.ok")));
        Assert.Contains("mod.gate.err", CaptureStderr(
            () => ProvideTelemetry.GetLogger("a").Error("mod.gate.err")));
    }

    [Fact]
    public void TheWarnRankGatesInfoOutAndWarnThrough()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_LEVEL", "WARN");
        Testing.ResetForTests();
        ProvideTelemetry.SetupTelemetry();

        Assert.Equal("", CaptureStderr(() => ProvideTelemetry.GetLogger("g").Info("gate.info.ok")));
        Assert.Contains("gate.warn.ok", CaptureStderr(
            () => ProvideTelemetry.GetLogger("g").Warn("gate.warn.ok")));
    }

    [Fact]
    public void TheConsoleRendererNeverLeaksReservedKeysAsExtras()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_INCLUDE_TIMESTAMP", "true");
        Testing.ResetForTests();
        ProvideTelemetry.SetupTelemetry();

        var raw = CaptureStderr(() => ProvideTelemetry.GetLogger("fmt").Info(
            "order.create.ok", new Dictionary<string, object?> { ["count"] = 3 }));

        Assert.Contains("count=3", raw);
        Assert.DoesNotContain("level=", raw);
        Assert.DoesNotContain("message=", raw);
        Assert.DoesNotContain("timestamp=", raw);
    }

    [Fact]
    public void CaptureUsesTheLiveConfigNotTheDefaults()
    {
        Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", "svc-cap");
        Testing.ResetForTests();
        ProvideTelemetry.SetupTelemetry();

        var record = Capture.Error(new InvalidOperationException("boom"));

        Assert.Equal("svc-cap", record.ToWireEnvelope(false)["service"]);
    }
}
