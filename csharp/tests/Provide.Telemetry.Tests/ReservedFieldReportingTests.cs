// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Text.Json;
using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// <c>reserved_root_fields.replacement_reporting</c> in spec/telemetry-api.yaml,
/// and the contract case <c>reserved_root_fields_replacement_reported</c>.
/// </summary>
[Collection("Telemetry")]
public class ReservedFieldReportingTests
{
    public ReservedFieldReportingTests() => Testing.ResetForTests();

    private static void Configure(string version = "1.2.3")
    {
        Testing.ResetForTests();
        var config = TelemetryConfig.Default();
        config.ServiceName = "svc";
        config.Environment = "stage";
        config.Version = version;
        config.Logging.Format = "json";
        config.Logging.IncludeTimestamp = false;
        ProvideTelemetry.SetupTelemetry(config);
    }

    private static List<JsonElement> Emit(Dictionary<string, object?> fields)
    {
        var sw = new StringWriter();
        var orig = Console.Error;
        Console.SetError(sw);
        try
        {
            ProvideTelemetry.GetLogger("caller").Info("reserved.fields.ok", fields);
        }
        finally
        {
            Console.SetError(orig);
        }
        return sw.ToString()
            .Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Select(line => JsonDocument.Parse(line).RootElement.Clone())
            .ToList();
    }

    private static List<string> Warned(List<JsonElement> records) => records
        .Where(r => r.GetProperty("message").GetString() == ReservedFields.WarningEvent)
        .Select(r => r.GetProperty("field").GetString()!)
        .ToList();

    private static long Replacements() => ProvideTelemetry.GetHealthSnapshot().ReservedFieldReplacements;

    private static Dictionary<string, object?> Fields(params (string Key, object? Value)[] pairs) =>
        pairs.ToDictionary(p => p.Key, p => p.Value, StringComparer.Ordinal);

    [Fact]
    public void AReplacedFieldIsCountedAndWarnedAboutOnce()
    {
        try
        {
            Configure();
            var first = Emit(Fields(("version", "9.9.9"), ("env", "forged")));
            Assert.Equal(["env", "version"], Warned(first));
            var last = first[^1];
            Assert.Equal("reserved.fields.ok", last.GetProperty("message").GetString());
            Assert.Equal("1.2.3", last.GetProperty("version").GetString());
            Assert.Equal(2, Replacements());

            Assert.Empty(Warned(Emit(Fields(("version", "8.8.8")))));
            Assert.Equal(3, Replacements());
        }
        finally
        {
            Testing.ResetForTests();
        }
    }

    [Fact]
    public void TheWarningNamesTheFieldAndNeverTheValue()
    {
        try
        {
            Configure();
            var warning = Emit(Fields(("version", "secret-build-7")))[0];
            Assert.Equal(ReservedFields.WarningEvent, warning.GetProperty("message").GetString());
            Assert.Equal("version", warning.GetProperty("field").GetString());
            Assert.Equal("WARN", warning.GetProperty("level").GetString());
            Assert.Equal(ReservedFields.WarningLogger, warning.GetProperty("logger_name").GetString());
            Assert.DoesNotContain("secret-build-7", warning.GetRawText());
        }
        finally
        {
            Testing.ResetForTests();
        }
    }

    [Fact]
    public void EqualValuesAndUnstampedFieldsAreNotReplacements()
    {
        try
        {
            Configure();
            Emit(Fields(("version", "1.2.3"), ("service_name", "svc"), ("trace_id", "caller-trace")));
            Configure(version: "");
            Emit(Fields(("version", "9.9.9")));
            Assert.Equal(0, Replacements());
        }
        finally
        {
            Testing.ResetForTests();
        }
    }

    [Fact]
    public void EitherSpellingOfAnIdentityFieldAndALiveTraceIdCount()
    {
        try
        {
            Configure();
            ProvideTelemetry.SetTraceContext("aabbccdd11223344aabbccdd11223344", "aabb001122334455");
            var records = Emit(Fields(("service_name", "other"), ("environment", "forged"), ("span_id", "forged")));
            Assert.Equal(["service", "env", "span_id"], Warned(records));
            Assert.Equal(3, Replacements());
        }
        finally
        {
            Testing.ResetForTests();
        }
    }

    [Fact]
    public void ABoundValueCountsOnceAndNotForItsOwnWarning()
    {
        try
        {
            Configure();
            ProvideTelemetry.BindContext(Fields(("version", "bound")));
            Assert.Equal(["version"], Warned(Emit(Fields())));
            Assert.Equal(1, Replacements());
        }
        finally
        {
            Testing.ResetForTests();
        }
    }

    [Fact]
    public void ARefusedRecordIsNeitherCountedNorWarnedAbout()
    {
        try
        {
            Configure();
            ProvideTelemetry.SetSamplingPolicy("logs", new SamplingPolicy { DefaultRate = 0 });
            Assert.Empty(Emit(Fields(("version", "9.9.9"))));
            Assert.Equal(0, Replacements());
        }
        finally
        {
            Testing.ResetForTests();
        }
    }

    [Fact]
    public void ResetForgetsWhichFieldsWereWarnedAbout()
    {
        try
        {
            Configure();
            Assert.Equal(["version"], Warned(Emit(Fields(("version", "9.9.9")))));
            ReservedFields.Reset();
            Assert.Equal(["version"], Warned(Emit(Fields(("version", "9.9.9")))));
        }
        finally
        {
            Testing.ResetForTests();
        }
    }
}
