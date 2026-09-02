// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Text.Json;

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// The logger's own decisions: level gating, per-module levels, field merging,
/// schema diagnostics, message sanitization and the three render forms.
/// </summary>
/// <remarks>
/// Assertions run against the rendered line, which is what an operator actually
/// reads. Asserting that <c>Info()</c> returned would pass against a logger that
/// wrote nothing at all.
/// </remarks>
[Collection("Telemetry")]
public class LoggerEmissionTests : IDisposable
{
    private static readonly string[] TouchedVariables =
    {
        "PROVIDE_LOG_FORMAT", "PROVIDE_LOG_LEVEL", "PROVIDE_LOG_INCLUDE_TIMESTAMP",
        "PROVIDE_LOG_SANITIZE", "PROVIDE_TELEMETRY_REQUIRED_KEYS",
    };

    public LoggerEmissionTests()
    {
        ClearEnvironment();
        Testing.ResetForTests();
    }

    public void Dispose()
    {
        ClearEnvironment();
        Testing.ResetForTests();
    }

    private static void ClearEnvironment()
    {
        foreach (var key in TouchedVariables) Environment.SetEnvironmentVariable(key, null);
    }

    /// <summary>Run an action with stderr captured, returning the emitted lines.</summary>
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

    /// <summary>Reset into a running JSON-format runtime.</summary>
    private static void StartJsonRuntime()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");
        Testing.ResetForTests();
        ProvideTelemetry.SetupTelemetry();
    }

    private static Dictionary<string, JsonElement> CaptureJson(Action action)
    {
        StartJsonRuntime();
        return CaptureJsonOnRunningRuntime(action);
    }

    private static Dictionary<string, JsonElement> CaptureJsonOnRunningRuntime(Action action)
    {
        var line = Assert.Single(CaptureStderr(action));
        return JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(line)!;
    }

    // ── level methods ────────────────────────────────────────────────────────

    [Theory]
    [InlineData("Trace", "TRACE")]
    [InlineData("Debug", "DEBUG")]
    [InlineData("Info", "INFO")]
    [InlineData("Warn", "WARN")]
    [InlineData("Warning", "WARNING")]
    [InlineData("Error", "ERROR")]
    [InlineData("Critical", "CRITICAL")]
    public void EveryLevelMethodEmitsItsOwnLevelName(string method, string expected)
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_LEVEL", "TRACE");
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");
        Testing.ResetForTests();
        ProvideTelemetry.SetupTelemetry();
        var logger = ProvideTelemetry.GetLogger("levels");
        // The two trailing parameters are the compiler-supplied callsite, which
        // reflection cannot fill in; passing an empty path is how a caller with
        // no source position of its own says so, and the record then omits
        // filename/lineno. LoggerCallsiteTests covers the populated case.
        var emit = typeof(Logger).GetMethod(
            method,
            new[]
            {
                typeof(string), typeof(IReadOnlyDictionary<string, object?>),
                typeof(string), typeof(int),
            })!;

        var line = Assert.Single(CaptureStderr(
            () => emit.Invoke(logger, new object?[] { "level.check.ok", null, "", 0 })));

        var record = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(line)!;
        Assert.Equal(expected, record["level"].GetString());
        Assert.Equal("level.check.ok", record["message"].GetString());
    }

    [Fact]
    public void LevelsBelowTheConfiguredThresholdEmitNothing()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_LEVEL", "WARNING");
        Testing.ResetForTests();
        ProvideTelemetry.SetupTelemetry();
        var logger = ProvideTelemetry.GetLogger("gate");

        var lines = CaptureStderr(() =>
        {
            logger.Trace("a.b.c");
            logger.Debug("a.b.c");
            logger.Info("a.b.c");
            logger.Warn("a.b.warn");
            logger.Critical("a.b.crit");
        });

        Assert.Equal(2, lines.Length);
        Assert.Contains("a.b.warn", lines[0]);
        Assert.Contains("a.b.crit", lines[1]);
        // A suppressed line is not a drop: it never entered the pipeline.
        Assert.Equal(0, Health.GetHealthSnapshot().LogsDropped);
        Assert.Equal(2, Health.GetHealthSnapshot().LogsEmitted);
    }

    [Fact]
    public void UnknownLevelNamesRankAsInfoOnBothSidesOfTheComparison()
    {
        ProvideTelemetry.SetupTelemetry();
        ProvideTelemetry.UpdateRuntimeConfig(new RuntimeOverrides { LogLevel = "SHOUTY" });
        var logger = ProvideTelemetry.GetLogger("gate");

        var lines = CaptureStderr(() =>
        {
            logger.Debug("a.b.debug");
            logger.Info("a.b.info");
        });

        var line = Assert.Single(lines);
        Assert.Contains("a.b.info", line);
    }

    // ── per-module levels ────────────────────────────────────────────────────

    [Fact]
    public void ModuleLevels_TheLongestMatchingPrefixWins()
    {
        ProvideTelemetry.SetupTelemetry();
        ProvideTelemetry.UpdateRuntimeConfig(new RuntimeOverrides
        {
            LogLevel = "ERROR",
            ModuleLevels = new Dictionary<string, string>
            {
                ["app"] = "WARNING",
                ["app.db"] = "DEBUG",
            },
        });

        var lines = CaptureStderr(() =>
        {
            // "app.db.pool" matches both prefixes; the longer one sets DEBUG.
            ProvideTelemetry.GetLogger("app.db.pool").Debug("db.query.ok");
            // "app.http" matches only "app": WARNING, so DEBUG is suppressed.
            ProvideTelemetry.GetLogger("app.http").Debug("http.request.ok");
            ProvideTelemetry.GetLogger("app.http").Warn("http.request.slow");
            // "other" matches nothing and falls back to the root ERROR level.
            ProvideTelemetry.GetLogger("other").Warn("other.thing.ok");
            ProvideTelemetry.GetLogger("other").Error("other.thing.bad");
        });

        Assert.Equal(3, lines.Length);
        Assert.Contains("db.query.ok", lines[0]);
        Assert.Contains("http.request.slow", lines[1]);
        Assert.Contains("other.thing.bad", lines[2]);
    }

    [Fact]
    public void ModuleLevels_APrefixMustEndOnASegmentBoundary()
    {
        ProvideTelemetry.SetupTelemetry();
        ProvideTelemetry.UpdateRuntimeConfig(new RuntimeOverrides
        {
            LogLevel = "ERROR",
            ModuleLevels = new Dictionary<string, string> { ["app"] = "DEBUG" },
        });

        var lines = CaptureStderr(() =>
        {
            // "application" merely starts with "app"; it is not under it.
            ProvideTelemetry.GetLogger("application").Debug("app.like.ok");
            ProvideTelemetry.GetLogger("app").Debug("app.exact.ok");
        });

        var line = Assert.Single(lines);
        Assert.Contains("app.exact.ok", line);
    }

    // ── field merging ────────────────────────────────────────────────────────

    [Fact]
    public void CallerFieldsOutrankBoundContextFields()
    {
        StartJsonRuntime();
        Context.BindContext(new Dictionary<string, object?> { ["tenant"] = "bound", ["region"] = "eu" });

        var record = CaptureJsonOnRunningRuntime(() => ProvideTelemetry.GetLogger("merge").Info(
            "merge.fields.ok", new Dictionary<string, object?> { ["tenant"] = "explicit" }));

        Assert.Equal("explicit", record["tenant"].GetString());
        Assert.Equal("eu", record["region"].GetString());
    }

    // ── schema diagnostics ───────────────────────────────────────────────────

    [Fact]
    public void MissingRequiredKeysRideAlongAsASchemaErrorRatherThanThrowing()
    {
        Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_REQUIRED_KEYS", "user_id,tenant");

        var record = CaptureJson(() => ProvideTelemetry.GetLogger("schema").Info(
            "order.create.ok", new Dictionary<string, object?> { ["user_id"] = "u1" }));

        Assert.Equal("missing required key: tenant", record["_schema_error"].GetString());
        Assert.Equal("order.create.ok", record["message"].GetString());
    }

    [Fact]
    public void SatisfiedRequiredKeysLeaveNoSchemaErrorBehind()
    {
        Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_REQUIRED_KEYS", "user_id");

        var record = CaptureJson(() => ProvideTelemetry.GetLogger("schema").Info(
            "order.create.ok", new Dictionary<string, object?> { ["user_id"] = "u1" }));

        Assert.False(record.ContainsKey("_schema_error"));
    }

    [Fact]
    public void StrictSchemaReportsAMalformedEventNameWithoutFailingTheCall()
    {
        ProvideTelemetry.SetupTelemetry();
        ProvideTelemetry.SetStrictSchema(true);
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");
        ProvideTelemetry.UpdateRuntimeConfig(new RuntimeOverrides { LogFormat = "json", StrictSchema = true });

        var line = Assert.Single(CaptureStderr(
            () => ProvideTelemetry.GetLogger("schema").Info("NotAnEventName")));

        var record = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(line)!;
        Assert.Equal("event name requires 3-5 segments, got 1", record["_schema_error"].GetString());
    }

    [Fact]
    public void TheSchemaDiagnosticIsAttachedAfterRedactionSoItIsNeverItselfRedacted()
    {
        // _schema_error is added downstream of the sanitizer on purpose: routed
        // through it, the message would be treated as a caller field.
        Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_REQUIRED_KEYS", "token");

        var record = CaptureJson(() => ProvideTelemetry.GetLogger("schema").Info("order.create.ok"));

        Assert.Equal("missing required key: token", record["_schema_error"].GetString());
        Assert.NotEqual(Pii.Redacted, record["_schema_error"].GetString());
    }

    // ── message sanitization ─────────────────────────────────────────────────

    [Fact]
    public void ASecretInTheMessageItselfIsReplacedWhenSanitizationIsOn()
    {
        var record = CaptureJson(
            () => ProvideTelemetry.GetLogger("pii").Info("AKIAIOSFODNN7EXAMPLE"));

        Assert.Equal(Pii.Redacted, record["message"].GetString());
    }

    [Fact]
    public void ASecretInTheMessageSurvivesWhenSanitizationIsOff()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_SANITIZE", "false");

        var record = CaptureJson(
            () => ProvideTelemetry.GetLogger("pii").Info("AKIAIOSFODNN7EXAMPLE"));

        Assert.Equal("AKIAIOSFODNN7EXAMPLE", record["message"].GetString());
    }

    // ── error fingerprints ───────────────────────────────────────────────────

    [Fact]
    public void TheExceptionOverloadAttachesTheStableFingerprint()
    {
        Exception thrown;
        try { throw new InvalidOperationException("boom"); }
        catch (InvalidOperationException caught) { thrown = caught; }

        var record = CaptureJson(
            () => ProvideTelemetry.GetLogger("err").Error("op.run.failed", thrown));

        Assert.Equal(
            Fingerprint.ComputeErrorFingerprint(thrown), record["error_fingerprint"].GetString());
        Assert.Equal("ERROR", record["level"].GetString());
        Assert.Equal("op.run.failed", record["message"].GetString());
    }

    [Fact]
    public void TheExceptionOverloadRejectsANullException()
    {
        Assert.Throws<ArgumentNullException>(
            () => ProvideTelemetry.GetLogger("err").Error("op.run.failed", (Exception)null!));
    }

    [Fact]
    public void TheMessageOnlyOverloadCarriesNoFingerprint()
    {
        var record = CaptureJson(() => ProvideTelemetry.GetLogger("err").Error("op.run.failed"));

        Assert.False(record.ContainsKey("error_fingerprint"));
    }

    // ── render forms ─────────────────────────────────────────────────────────

    [Fact]
    public void ConsoleFormatRendersUnquotedKeyValuePairsAfterTheBracketedLevel()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "console");
        Environment.SetEnvironmentVariable("PROVIDE_LOG_INCLUDE_TIMESTAMP", "false");
        Testing.ResetForTests();
        ProvideTelemetry.SetupTelemetry();

        var line = Assert.Single(CaptureStderr(() => ProvideTelemetry.GetLogger("fmt").Info(
            "order.create.ok", new Dictionary<string, object?> { ["count"] = 3 })));

        Assert.StartsWith("[INFO] order.create.ok ", line);
        Assert.Contains("count=3", line);
        Assert.Contains("logger_name=fmt", line);
        Assert.DoesNotContain("count=\"3\"", line);
    }

    [Fact]
    public void PrettyFormatQuotesTheValues()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "pretty");
        Environment.SetEnvironmentVariable("PROVIDE_LOG_INCLUDE_TIMESTAMP", "false");
        Testing.ResetForTests();
        ProvideTelemetry.SetupTelemetry();

        var line = Assert.Single(CaptureStderr(() => ProvideTelemetry.GetLogger("fmt").Info(
            "order.create.ok", new Dictionary<string, object?> { ["count"] = 3 })));

        Assert.Contains("count=\"3\"", line);
    }

    [Fact]
    public void TimestampsPrefixTheTextLineWhenEnabled()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "console");
        Environment.SetEnvironmentVariable("PROVIDE_LOG_INCLUDE_TIMESTAMP", "true");
        Testing.ResetForTests();
        ProvideTelemetry.SetupTelemetry();

        var line = Assert.Single(CaptureStderr(
            () => ProvideTelemetry.GetLogger("fmt").Info("order.create.ok")));

        Assert.Matches(@"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z \[INFO\] order\.create\.ok", line);
    }

    [Fact]
    public void ATextLineWithNoExtraFieldsHasNoTrailingSeparator()
    {
        // The root logger contributes no logger_name and every identity field is
        // empty, so "extras" really is empty and the line must not end in a
        // dangling space. The callsite is switched off for the same reason:
        // filename/lineno are extras like any other, and this test is about the
        // no-extras line. Run with no backend factory: this is the core-package
        // -alone deployment, and OTel's resource builder rejects an empty
        // service name outright.
        Testing.ResetForTests();
        TelemetryBackendRegistry.Register(_ => null!);
        try
        {
            var config = TelemetryConfig.Default();
            config.Logging.Format = "console";
            config.Logging.IncludeTimestamp = false;
            config.Logging.IncludeCaller = false;
            config.ServiceName = "";
            config.Environment = "";
            config.Version = "";
            ProvideTelemetry.SetupTelemetry(config);
            Assert.Null(Setup.CurrentBackend);

            var line = Assert.Single(CaptureStderr(
                () => ProvideTelemetry.GetLogger("").Info("order.create.ok")));

            Assert.Equal("[INFO] order.create.ok", line);
        }
        finally
        {
            // The registry is process-wide and the suite's module initializer
            // installs the OTLP factory once, so a test that displaces it has to
            // put it back or every later test runs without a backend.
            Provide.Telemetry.OpenTelemetry.OpenTelemetryBackendRegistration.Register();
            Testing.ResetForTests();
        }
    }

    [Fact]
    public void GetLoggerTreatsANullNameAsTheRootLogger()
    {
        var record = CaptureJson(() => ProvideTelemetry.GetLogger(null!).Info("root.log.ok"));

        Assert.False(record.ContainsKey("logger_name"));
    }

    // ── Capture ──────────────────────────────────────────────────────────────

    [Fact]
    public void CaptureError_BuildsTheRecordWithoutEmittingIt()
    {
        ProvideTelemetry.SetupTelemetry();
        Context.SetTraceContext("0af7651916cd43dd8448eb211c80319c", "b7ad6b7169203331");
        Exception thrown;
        try { throw new InvalidOperationException("boom"); }
        catch (InvalidOperationException caught) { thrown = caught; }

        CanonicalLogRecord record = null!;
        var lines = CaptureStderr(() => record = Capture.Error(thrown));

        Assert.Empty(lines);
        Assert.Equal("ERROR", record.Level);
        Assert.Equal("boom", record.Event);
        Assert.Equal("0af7651916cd43dd8448eb211c80319c", record.TraceId);
        Assert.Equal("b7ad6b7169203331", record.SpanId);
        Assert.Equal(Fingerprint.ComputeErrorFingerprint(thrown), record.ErrorFingerprint);
    }

    [Fact]
    public void CaptureError_TakesAnExplicitMessageAndFieldsOverTheExceptionsOwn()
    {
        ProvideTelemetry.SetupTelemetry();
        var record = Capture.Error(
            new InvalidOperationException("boom"),
            "order.create.failed",
            new Dictionary<string, object?> { ["order_id"] = "o1" });

        Assert.Equal("order.create.failed", record.Event);
        Assert.Equal("o1", record.Attributes["order_id"]);
    }

    [Fact]
    public void CaptureError_RejectsANullException()
    {
        Assert.Throws<ArgumentNullException>(() => Capture.Error(null!));
    }

    [Fact]
    public void CaptureError_UsesTheDefaultConfigBeforeAnyRuntimeExists()
    {
        // No SetupTelemetry: Capture must still produce a well-formed record
        // rather than faulting on a missing runtime config.
        var record = Capture.Error(new InvalidOperationException("boom"));

        Assert.Equal("provide-service", record.ServiceName);
        Assert.Null(record.TraceId);
    }
}
