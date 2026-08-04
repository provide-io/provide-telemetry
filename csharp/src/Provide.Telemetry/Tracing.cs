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

public sealed class NoOpSpan : ISpan
{
    private readonly QueueTicket? _ticket;
    private bool _disposed;

    public string TraceId { get; }
    public string SpanId { get; }

    public NoOpSpan(string? traceId = null, string? spanId = null, QueueTicket? ticket = null)
    {
        TraceId = string.IsNullOrEmpty(traceId) ? RandomId(32) : traceId;
        SpanId = string.IsNullOrEmpty(spanId) ? RandomId(16) : spanId;
        _ticket = ticket;
    }

    public void SetAttribute(string key, object? value) { }
    public void RecordException(Exception ex) { }
    public void SetStatus(string status, string? description = null) { }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        // Hold ticket for span lifetime (parity with OtelSpan / live path).
        Backpressure.Release(_ticket);
    }

    private static string RandomId(int hexLen)
    {
        var bytes = new byte[hexLen / 2];
        Random.Shared.NextBytes(bytes);
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }
}

public sealed class NoOpTracer : ITracer
{
    public ISpan StartSpan(string name)
    {
        if (!Setup.IsTracingEnabled())
        {
            return DroppedSpan();
        }
        // Dropped spans: consent / sampling / backpressure reject without a live span.
        if (!Consent.ShouldAllow(Signals.Traces, ""))
        {
            return DroppedSpan();
        }
        if (!Sampling.ShouldSample(Signals.Traces, name))
        {
            return DroppedSpan();
        }
        var ticket = Backpressure.TryAcquire(Signals.Traces);
        if (ticket is null)
        {
            // TryAcquire returns null when limited queue is full (or unknown signal).
            var max = Backpressure.GetQueuePolicy().TracesMaxSize;
            if (max > 0) return DroppedSpan();
        }
        var span = new NoOpSpan(ticket: ticket);
        Context.SetTraceContext(span.TraceId, span.SpanId);
        Health.RecordEmitted(Signals.Traces);
        return span;
    }

    private static NoOpSpan DroppedSpan() =>
        new("00000000000000000000000000000000", "0000000000000000");
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
            return Otel.OtelBackend.GetTracer() ?? _default;
        }
    }

    public static ITracer GetTracer(string name = "")
    {
        Setup.EnsureLazyInit();
        return Otel.OtelBackend.GetTracer(name) ?? _default;
    }

    /// <summary>
    /// Idiomatic span wrapper (decorator equivalent). Runs action inside a span
    /// and disposes the span when the action returns. Does not return the disposed span.
    /// </summary>
    public static void Trace(string name, Action action)
    {
        using var span = GetTracer().StartSpan(name);
        action();
    }

    public static T Trace<T>(string name, Func<T> func)
    {
        using var span = GetTracer().StartSpan(name);
        return func();
    }

    public static (string TraceId, string SpanId) GetTraceContext() => Context.GetTraceContext();

    public static void SetTraceContext(string traceId, string spanId) =>
        Context.SetTraceContext(traceId, spanId);

    internal static void Reset() => _default = new NoOpTracer();
}
