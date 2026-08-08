// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

[Collection("Telemetry")]
public class CanonicalLogRecordTests
{
    public CanonicalLogRecordTests() => Testing.ResetForTests();

    [Fact]
    public void LocalErrorRecordUsesCanonicalSnakeCaseEnvelope()
    {
        ProvideTelemetry.SetupTelemetry();
        ProvideTelemetry.SetTraceContext("0af7651916cd43dd8448eb211c80319c", "b7ad6b7169203331");

        var record = Capture.Error(new InvalidOperationException("boom"));

        Assert.Contains(CanonicalLogRecord.ServiceNameKey, record.Attributes.Keys);
        Assert.Contains(CanonicalLogRecord.TraceIdKey, record.Attributes.Keys);
        Assert.Contains(CanonicalLogRecord.ErrorFingerprintKey, record.Attributes.Keys);
        Assert.DoesNotContain("service.name", record.Attributes.Keys);
        Assert.DoesNotContain("trace.id", record.Attributes.Keys);
        Assert.DoesNotContain("span.id", record.Attributes.Keys);
    }

    [Fact]
    public void ErrorRecordCarriesTheSharedFingerprintAlgorithm()
    {
        var error = new InvalidOperationException("boom");
        var record = Capture.Error(error);
        Assert.Equal(Fingerprint.ComputeErrorFingerprint(error), record.ErrorFingerprint);
        Assert.Equal(12, record.ErrorFingerprint!.Length);
    }

    [Fact]
    public void WireEnvelopeUsesTheCanonicalLogLineVocabulary()
    {
        var cfg = TelemetryConfig.Default();
        cfg.ServiceName = "checkout";
        cfg.Environment = "prod";
        cfg.Version = "1.2.3";

        var record = CanonicalLogRecord.Create(
            DateTimeOffset.UnixEpoch, "INFO", "order.created", "orders", cfg,
            "0af7651916cd43dd8448eb211c80319c", "b7ad6b7169203331",
            new Dictionary<string, object?> { ["order_id"] = "A1" });

        var envelope = record.ToWireEnvelope(includeTimestamp: true);

        // log_output_format in spec/behavioral_fixtures.yaml: the envelope's
        // identity keys are the terse ones, and the dotted spellings it lists as
        // noise appear nowhere.
        Assert.Equal("checkout", envelope["service"]);
        Assert.Equal("prod", envelope["env"]);
        Assert.Equal("1.2.3", envelope["version"]);
        Assert.Equal("0af7651916cd43dd8448eb211c80319c", envelope["trace_id"]);
        Assert.Equal("b7ad6b7169203331", envelope["span_id"]);
        Assert.Equal("orders", envelope["logger_name"]);
        Assert.Equal("A1", envelope["order_id"]);
        Assert.DoesNotContain("service.name", envelope.Keys);
        Assert.DoesNotContain("service_name", envelope.Keys);
        Assert.DoesNotContain("trace.id", envelope.Keys);
    }

    [Fact]
    public void EnvelopeTimestampMatchesTheFixturePattern()
    {
        var record = CanonicalLogRecord.Create(
            DateTimeOffset.UnixEpoch, "INFO", "e", "", TelemetryConfig.Default(), "", "",
            new Dictionary<string, object?>());
        var envelope = record.ToWireEnvelope(includeTimestamp: true);
        Assert.Matches(@"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", (string)envelope["timestamp"]!);
    }

    [Fact]
    public void EnvelopeOmitsTimestampWhenDisabled()
    {
        var record = CanonicalLogRecord.Create(
            DateTimeOffset.UnixEpoch, "INFO", "e", "", TelemetryConfig.Default(), "", "",
            new Dictionary<string, object?>());
        Assert.DoesNotContain("timestamp", record.ToWireEnvelope(includeTimestamp: false).Keys);
    }

    [Fact]
    public void IdentityAttributesOutrankACallerFieldOfTheSameName()
    {
        var cfg = TelemetryConfig.Default();
        cfg.ServiceName = "real-service";
        var record = CanonicalLogRecord.Create(
            DateTimeOffset.UnixEpoch, "INFO", "e", "", cfg, "", "",
            new Dictionary<string, object?> { [CanonicalLogRecord.ServiceNameKey] = "impostor" });
        Assert.Equal("real-service", record.Attributes[CanonicalLogRecord.ServiceNameKey]);
    }

    [Fact]
    public void AbsentTraceContextLeavesTheKeysOut()
    {
        var record = CanonicalLogRecord.Create(
            DateTimeOffset.UnixEpoch, "INFO", "e", "", TelemetryConfig.Default(), "", "",
            new Dictionary<string, object?>());
        Assert.DoesNotContain(CanonicalLogRecord.TraceIdKey, record.Attributes.Keys);
        Assert.Null(record.TraceId);
        Assert.Null(record.ErrorFingerprint);
    }
}
