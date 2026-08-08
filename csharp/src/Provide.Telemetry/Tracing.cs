// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

namespace Provide.Telemetry;

public interface ISpan : IDisposable
{
    void SetAttribute(string key, object? value);
    void RecordException(Exception ex);
    void SetStatus(string status, string? description = null);
    string TraceId { get; }
    string SpanId { get; }
}

public interface ITracer
{
    ISpan StartSpan(string name);
}

/// <summary>Span used when no backend tracer is installed, and for dropped spans.</summary>
public sealed class NoOpSpan : ISpan
{
    private readonly SignalAdmission _admission;
    private readonly IDisposable? _contextScope;
    private int _disposed;

    public string TraceId { get; }
    public string SpanId { get; }

    /// <summary>
    /// Construct a span. Internal: a span is only ever handed out by a tracer,
    /// which is what pairs it with the queue ticket and context scope it owns.
    /// </summary>
    internal NoOpSpan(string? traceId, string? spanId, SignalAdmission admission, IDisposable? contextScope)
    {
        TraceId = string.IsNullOrEmpty(traceId) ? NewId(32) : traceId;
        SpanId = string.IsNullOrEmpty(spanId) ? NewId(16) : spanId;
        _admission = admission;
        _contextScope = contextScope;
    }

    /// <summary>The all-zero span returned when admission control refused.</summary>
    internal static NoOpSpan Dropped() =>
        new("00000000000000000000000000000000", "0000000000000000", default, null);

    public void SetAttribute(string key, object? value) { }
    public void RecordException(Exception ex) { }
    public void SetStatus(string status, string? description = null) { }

    /// <summary>
    /// End the span, restore the enclosing trace context, and return the ticket.
    /// </summary>
    /// <remarks>
    /// Idempotent, so a span disposed both by a <c>using</c> and by an explicit
    /// call releases one ticket and unwinds one level of context.
    /// </remarks>
    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0) return;
        _contextScope?.Dispose();
        _admission.Release();
    }

    /// <summary>A random lowercase-hex identifier of the given character length.</summary>
    internal static string NewId(int hexLen)
    {
        var bytes = new byte[hexLen / 2];
        Random.Shared.NextBytes(bytes);
        return Convert.ToHexStringLower(bytes);
    }
}

public sealed class NoOpTracer : ITracer
{
    public ISpan StartSpan(string name)
    {
        var admission = SignalPipeline.Admit(Signals.Traces, name);
        if (!admission.Admitted) return NoOpSpan.Dropped();

        // Identifiers first, so the scope that will restore the caller's context
        // is opened with the values this span is about to publish.
        var traceId = NoOpSpan.NewId(32);
        var spanId = NoOpSpan.NewId(16);
        var scope = Context.PushTraceContext(traceId, spanId);
        Health.RecordEmitted(Signals.Traces);
        return new NoOpSpan(traceId, spanId, admission, scope);
    }
}

public static class Tracing
{
    private static ITracer _default = new NoOpTracer();

    /// <summary>Pre-built default tracer instance.</summary>
    public static ITracer Tracer
    {
        get
        {
            Setup.EnsureLazyInit();
            return Setup.CurrentBackend?.GetTracer("") ?? _default;
        }
    }

    public static ITracer GetTracer(string name = "")
    {
        Setup.EnsureLazyInit();
        return Setup.CurrentBackend?.GetTracer(name) ?? _default;
    }

    /// <summary>
    /// Idiomatic span wrapper (decorator equivalent). Runs action inside a span
    /// and disposes the span when the action returns.
    /// </summary>
    public static void Trace(string name, Action action)
    {
        ArgumentNullException.ThrowIfNull(action);
        using var span = GetTracer().StartSpan(name);
        action();
    }

    public static T Trace<T>(string name, Func<T> func)
    {
        ArgumentNullException.ThrowIfNull(func);
        using var span = GetTracer().StartSpan(name);
        return func();
    }

    public static (string TraceId, string SpanId) GetTraceContext() => Context.GetTraceContext();

    public static void SetTraceContext(string traceId, string spanId) =>
        Context.SetTraceContext(traceId, spanId);

    internal static void Reset() => _default = new NoOpTracer();
}
