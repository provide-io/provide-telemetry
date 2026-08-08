// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.


namespace Provide.Telemetry;

/// <summary>Async-local bound fields, session, and trace context.</summary>
public static class Context
{
    private static readonly AsyncLocal<Dictionary<string, object?>?> Bound = new();
    private static readonly AsyncLocal<(string TraceId, string SpanId)?> Trace = new();
    private static readonly AsyncLocal<PropagationContext?> Propagation = new();
    private static readonly AsyncLocal<string?> SessionId = new();

    public static void BindContext(IReadOnlyDictionary<string, object?> fields)
    {
        // Functional/Minimal/None consent blocks context/baggage binding (polyglot).
        if (!Consent.ShouldAllow(Signals.Context, "")) return;
        var current = Bound.Value is null
            ? new Dictionary<string, object?>(StringComparer.Ordinal)
            : new Dictionary<string, object?>(Bound.Value, StringComparer.Ordinal);
        foreach (var (k, v) in fields)
        {
            current[k] = v;
        }
        Bound.Value = current;
    }

    public static void UnbindContext(params string[] keys)
    {
        if (Bound.Value is null) return;
        var current = new Dictionary<string, object?>(Bound.Value, StringComparer.Ordinal);
        foreach (var k in keys) current.Remove(k);
        Bound.Value = current;
    }

    public static void ClearContext()
    {
        Bound.Value = null;
        Trace.Value = null;
        Propagation.Value = null;
    }

    public static IReadOnlyDictionary<string, object?> GetBoundFields()
    {
        return Bound.Value is null
            ? new Dictionary<string, object?>(StringComparer.Ordinal)
            : new Dictionary<string, object?>(Bound.Value, StringComparer.Ordinal);
    }

    public static void SetTraceContext(string traceId, string spanId)
    {
        Trace.Value = (traceId ?? "", spanId ?? "");
    }

    /// <summary>
    /// Set the trace context and hand back a scope that restores the previous one.
    /// </summary>
    /// <remarks>
    /// Spans nest, so ending one must reveal its parent rather than clearing the
    /// slot: an inner span that reset the context to empty left every subsequent
    /// log line in the outer span untraced. The returned scope captures the
    /// predecessor before the write and is safe to dispose more than once.
    /// </remarks>
    public static IDisposable PushTraceContext(string traceId, string spanId)
    {
        var predecessor = Trace.Value;
        Trace.Value = (traceId ?? "", spanId ?? "");
        return new AsyncLocalScope<(string TraceId, string SpanId)?>(Trace, predecessor);
    }

    /// <summary>
    /// Bind fields and hand back a scope that restores the previous bindings.
    /// </summary>
    public static IDisposable PushContext(IReadOnlyDictionary<string, object?> fields)
    {
        var predecessor = Bound.Value;
        BindContext(fields);
        return new AsyncLocalScope<Dictionary<string, object?>?>(Bound, predecessor);
    }

    public static (string TraceId, string SpanId) GetTraceContext()
    {
        return Trace.Value ?? ("", "");
    }

    internal static void SetPropagation(PropagationContext pc) => Propagation.Value = pc;

    public static PropagationContext GetPropagationContext() => Propagation.Value ?? new PropagationContext();

    public static void BindSessionContext(string sessionId)
    {
        SessionId.Value = sessionId;
        BindContext(new Dictionary<string, object?> { ["session_id"] = sessionId });
    }

    public static string GetSessionID() => SessionId.Value ?? "";

    public static void ClearSessionContext()
    {
        SessionId.Value = null;
        UnbindContext("session_id");
    }

    internal static void Reset()
    {
        Bound.Value = null;
        Trace.Value = null;
        Propagation.Value = null;
        SessionId.Value = null;
    }
}
