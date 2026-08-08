// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Security.Cryptography;
using System.Text;

namespace Provide.Telemetry;

/// <summary>One redaction the PII engine performed, awaiting a receipt.</summary>
/// <param name="FieldPath">Dotted path of the field that was changed.</param>
/// <param name="Action">Redaction mode applied — redact, drop, hash or truncate.</param>
/// <param name="Original">The value as captured, before the change.</param>
internal sealed record PendingRedaction(string FieldPath, string Action, object? Original);

/// <summary>Destination for governance receipts.</summary>
/// <remarks>
/// <see cref="Emit"/> returns false to reject a receipt. Returning false and
/// throwing are equivalent: both count a failure. An implementation must not
/// log — see <see cref="Receipts.Emit"/>.
/// </remarks>
public interface IReceiptSink
{
    /// <summary>Deliver one receipt; false means rejected.</summary>
    bool Emit(RedactionReceipt receipt);
}

/// <summary>Thrown when receipts are enabled in production with nowhere to send them.</summary>
public sealed class MissingReceiptSinkError : TelemetryError
{
    public MissingReceiptSinkError()
        : base("receipts are enabled but no IReceiptSink is configured; generated receipts "
               + "would be computed and then discarded. Pass a sink, or disable receipts.")
    {
    }
}

/// <summary>In-memory sink for tests, bounded at <see cref="Capacity"/> receipts.</summary>
/// <remarks>
/// Only the test collector is capped. A production sink is the caller's own
/// durable destination, and silently discarding audit records to stay under a
/// memory budget is not a decision this library gets to make for them.
/// </remarks>
public sealed class TestReceiptCollector : IReceiptSink
{
    /// <summary>Retention cap, shared with the other SDKs.</summary>
    public const int Capacity = 1024;

    private readonly object _gate = new();
    private readonly Queue<RedactionReceipt> _receipts = new();

    public bool Emit(RedactionReceipt receipt)
    {
        lock (_gate)
        {
            if (_receipts.Count == Capacity) _receipts.Dequeue();
            _receipts.Enqueue(receipt);
        }
        return true;
    }

    /// <summary>Receipts collected so far, oldest first.</summary>
    public IReadOnlyList<RedactionReceipt> Receipts
    {
        get { lock (_gate) { return _receipts.ToList(); } }
    }

    internal void Clear()
    {
        lock (_gate) { _receipts.Clear(); }
    }
}

/// <summary>Cryptographic redaction receipts.</summary>
public static class Receipts
{
    private static readonly object Gate = new();
    private static readonly TestReceiptCollector TestCollector = new();
    private static bool _enabled;
    private static bool _testMode;
    private static string _signingKey = "";
    private static string _serviceName = "";
    private static IReceiptSink? _sink;

    /// <summary>Enable or disable receipt generation.</summary>
    /// <remarks>
    /// Enabling outside test mode without a sink throws rather than proceeding.
    /// The previous behavior computed a full signed receipt for every redaction
    /// and dropped it on the floor, so a service could believe it had an audit
    /// trail and have none.
    /// </remarks>
    public static void EnableReceipts(
        bool enabled, string signingKey = "", string serviceName = "", IReceiptSink? sink = null)
    {
        lock (Gate)
        {
            if (enabled && !_testMode && sink is null) throw new MissingReceiptSinkError();
            _enabled = enabled;
            _signingKey = signingKey ?? "";
            _serviceName = serviceName ?? "";
            _sink = sink;
            if (!enabled) TestCollector.Clear();
        }
    }

    /// <summary>
    /// Build a receipt over <paramref name="input"/>, canonicalizing and signing it.
    /// </summary>
    /// <remarks>
    /// Every identity-bearing field is a parameter rather than generated here so
    /// the fixture vectors can be reproduced exactly.
    /// </remarks>
    public static RedactionReceipt SignAt(
        object? input,
        string signingKey,
        string receiptId,
        string timestamp,
        string fieldPath,
        string action,
        string serviceName = "")
    {
        var originalHash = Convert.ToHexStringLower(
            SHA256.HashData(Encoding.UTF8.GetBytes(CanonicalJson.Serialize(input))));
        var payload = Payload(receiptId, timestamp, fieldPath, action, originalHash);
        var signature = string.IsNullOrEmpty(signingKey)
            ? ""
            : Convert.ToHexStringLower(HMACSHA256.HashData(
                Encoding.UTF8.GetBytes(signingKey), Encoding.UTF8.GetBytes(payload)));

        return new RedactionReceipt
        {
            ReceiptId = receiptId,
            FieldPath = fieldPath,
            Action = action,
            ServiceName = serviceName,
            Timestamp = timestamp,
            OriginalHash = originalHash,
            Hmac = signature,
        };
    }

    /// <summary>The canonical receipt payload, in the byte order every SDK signs.</summary>
    public static string Payload(
        string receiptId, string timestamp, string fieldPath, string action, string originalHash) =>
        string.Join("|", receiptId, timestamp, fieldPath, action, originalHash);

    /// <summary>
    /// Hand a receipt to its sink, counting refusals.
    /// </summary>
    /// <remarks>
    /// This path must never log. The logger is what produces redactions,
    /// redactions are what produce receipts, and a sink that fails on every
    /// receipt would drive an unbounded log to receipt to log cycle. A rejection
    /// is therefore recorded only as a counter, which
    /// <c>GetHealthSnapshot().ReceiptFailures</c> exposes.
    /// </remarks>
    public static void Emit(RedactionReceipt receipt, IReceiptSink sink)
    {
        ArgumentNullException.ThrowIfNull(sink);
        try
        {
            if (!sink.Emit(receipt)) Health.RecordReceiptFailure();
        }
        catch
        {
            // Counted, never logged, and never rethrown: a sink that throws must
            // not take the caller's log call down with it.
            Health.RecordReceiptFailure();
        }
    }

    /// <summary>Generate and deliver receipts for a batch of redactions.</summary>
    internal static void RecordAll(IReadOnlyList<PendingRedaction> redactions)
    {
        if (redactions.Count == 0) return;
        string signingKey, serviceName;
        IReceiptSink? sink;
        lock (Gate)
        {
            if (!_enabled) return;
            signingKey = _signingKey;
            serviceName = _serviceName;
            sink = _testMode ? TestCollector : _sink;
        }
        if (sink is null) return;

        foreach (var redaction in redactions)
        {
            var receipt = SignAt(
                redaction.Original,
                signingKey,
                Guid.NewGuid().ToString(),
                DateTimeOffset.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ",
                    System.Globalization.CultureInfo.InvariantCulture),
                redaction.FieldPath,
                redaction.Action,
                serviceName);
            Emit(receipt, sink);
        }
    }

    /// <summary>Receipts collected while test mode is on.</summary>
    public static IReadOnlyList<RedactionReceipt> GetEmittedReceiptsForTests() => TestCollector.Receipts;

    /// <summary>True when the built-in collector stands in for a configured sink.</summary>
    internal static bool IsTestMode
    {
        get { lock (Gate) { return _testMode; } }
    }

    internal static void SetTestMode(bool mode)
    {
        lock (Gate) { _testMode = mode; }
    }

    internal static void Reset()
    {
        lock (Gate)
        {
            _enabled = false;
            _signingKey = "";
            _serviceName = "";
            _sink = null;
            // Test isolation implies test mode: the suite must never exercise the
            // un-sinked path this module now rejects.
            _testMode = true;
            TestCollector.Clear();
        }
    }
}
