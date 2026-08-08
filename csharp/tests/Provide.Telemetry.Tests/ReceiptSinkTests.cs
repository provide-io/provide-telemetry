// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

[Collection("Telemetry")]
public class ReceiptSinkTests
{
    public ReceiptSinkTests() => Testing.ResetForTests();

    private sealed class RejectingSink : IReceiptSink
    {
        public int Calls { get; private set; }

        public bool Emit(RedactionReceipt receipt)
        {
            Calls++;
            return false;
        }
    }

    private sealed class ThrowingSink : IReceiptSink
    {
        public bool Emit(RedactionReceipt receipt) => throw new InvalidOperationException("sink is down");
    }

    private sealed class CountingSink : IReceiptSink
    {
        public int Calls { get; private set; }

        public bool Emit(RedactionReceipt receipt)
        {
            Calls++;
            return true;
        }
    }

    private static RedactionReceipt Sample() =>
        Receipts.SignAt("value", "key", "receipt-id", "2026-08-04T12:34:56.789Z", "user.email", "redact");

    [Fact]
    public void RejectingSinkCountsFailureWithoutLogging()
    {
        var sink = new RejectingSink();
        var captured = new StringWriter();
        var original = Console.Error;
        Console.SetError(captured);
        try
        {
            Receipts.Emit(Sample(), sink);
        }
        finally
        {
            Console.SetError(original);
        }

        Assert.Equal(1, sink.Calls);
        Assert.Equal(1L, ProvideTelemetry.GetHealthSnapshot().ReceiptFailures);
        // Never logged: the logger produces redactions, redactions produce
        // receipts, and a permanently failing sink would close that loop.
        Assert.Equal("", captured.ToString());
    }

    [Fact]
    public void ThrowingSinkIsCountedAndSwallowed()
    {
        Receipts.Emit(Sample(), new ThrowingSink());
        Assert.Equal(1L, ProvideTelemetry.GetHealthSnapshot().ReceiptFailures);
    }

    [Fact]
    public void AcceptingSinkCountsNoFailure()
    {
        var sink = new CountingSink();
        Receipts.Emit(Sample(), sink);
        Assert.Equal(1, sink.Calls);
        Assert.Equal(0L, ProvideTelemetry.GetHealthSnapshot().ReceiptFailures);
    }

    [Fact]
    public void HealthSnapshotCarriesTwentySixCanonicalFields()
    {
        // spec/behavioral_fixtures.yaml health_snapshot: eight per-signal fields
        // across three signals, plus setup_error and receipt_failures.
        var fields = typeof(HealthSnapshot)
            .GetProperties()
            .Select(p => p.Name)
            .ToList();
        Assert.Equal(26, fields.Count);
        Assert.Contains(nameof(HealthSnapshot.ReceiptFailures), fields);
        Assert.Equal(0L, ProvideTelemetry.GetHealthSnapshot().ReceiptFailures);
    }

    [Fact]
    public void EnablingReceiptsOutsideTestModeWithoutASinkIsRejected()
    {
        Receipts.SetTestMode(false);
        try
        {
            Assert.Throws<MissingReceiptSinkError>(
                () => ProvideTelemetry.EnableReceipts(true, "key", "svc"));
        }
        finally
        {
            Receipts.SetTestMode(true);
        }
    }

    [Fact]
    public void ProductionReceiptsReachTheConfiguredSink()
    {
        Receipts.SetTestMode(false);
        var sink = new CountingSink();
        try
        {
            Receipts.EnableReceipts(true, "key", "svc", sink);
            Pii.SanitizePayload(
                new Dictionary<string, object?> { ["password"] = "hunter2" }, enabled: true, maxDepth: 8);
            Assert.Equal(1, sink.Calls);
        }
        finally
        {
            Receipts.SetTestMode(true);
        }
    }

    [Fact]
    public void TestCollectorIsBoundedAtItsCapacity()
    {
        var collector = new TestReceiptCollector();
        for (var i = 0; i < TestReceiptCollector.Capacity + 10; i++)
        {
            collector.Emit(Receipts.SignAt(i, "key", $"id-{i}", "ts", "f", "redact"));
        }

        var receipts = collector.Receipts;
        Assert.Equal(TestReceiptCollector.Capacity, receipts.Count);
        // The oldest are evicted, so the newest survive — a bounded ring, not a
        // bounded prefix that stops recording once full.
        Assert.Equal($"id-{TestReceiptCollector.Capacity + 9}", receipts[^1].ReceiptId);
    }

    [Fact]
    public void RedactionsProduceOneReceiptEachThroughTheLogger()
    {
        ProvideTelemetry.EnableReceipts(true, "signing-key", "svc");
        ProvideTelemetry.SetupTelemetry();
        ProvideTelemetry.GetLogger("receipts").Info(
            "receipt.emit", new Dictionary<string, object?> { ["password"] = "hunter2", ["token"] = "abc" });

        var receipts = ProvideTelemetry.GetEmittedReceiptsForTests();
        Assert.Equal(2, receipts.Count);
        Assert.All(receipts, r => Assert.Equal("svc", r.ServiceName));
        Assert.All(receipts, r => Assert.NotEqual("", r.Hmac));
        Assert.Contains(receipts, r => r.FieldPath == "password");
        Assert.Contains(receipts, r => r.FieldPath == "token");
    }

    [Fact]
    public void DisabledReceiptsProduceNone()
    {
        ProvideTelemetry.EnableReceipts(false);
        Pii.SanitizePayload(
            new Dictionary<string, object?> { ["password"] = "hunter2" }, enabled: true, maxDepth: 8);
        Assert.Empty(ProvideTelemetry.GetEmittedReceiptsForTests());
    }
}
