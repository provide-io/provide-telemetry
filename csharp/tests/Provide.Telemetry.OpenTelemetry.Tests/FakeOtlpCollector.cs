// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Collections.Concurrent;
using System.Net;

namespace Provide.Telemetry.OpenTelemetry.Tests;

/// <summary>One request as it arrived on the wire.</summary>
public sealed record CapturedOtlpRequest(string Path, IReadOnlyDictionary<string, string> Headers, byte[] Body)
{
    /// <summary>True when the protobuf body embeds <paramref name="text"/> as UTF-8.</summary>
    public bool BodyContains(string text)
    {
        var needle = System.Text.Encoding.UTF8.GetBytes(text);
        return Body.AsSpan().IndexOf(needle) >= 0;
    }
}

/// <summary>
/// An in-process OTLP/HTTP endpoint the real exporters deliver to.
/// </summary>
/// <remarks>
/// This is the observation point for everything the SDK hides after
/// <c>Build()</c>: per-signal URL paths, the formatted header string, the
/// exporter option booleans, and whether a drain actually delivered. It
/// accepts anything, answers 200 with an empty protobuf body, and records
/// path + headers + body for assertions. Loopback only, ephemeral port,
/// no dependencies beyond the BCL.
/// </remarks>
public sealed class FakeOtlpCollector : IDisposable
{
    private readonly HttpListener _listener = new();
    private readonly ConcurrentQueue<CapturedOtlpRequest> _requests = new();
    private readonly CancellationTokenSource _stop = new();
    private readonly Task _pump;

    public FakeOtlpCollector()
    {
        // HttpListener cannot bind port 0; probe for a free port instead.
        var attempts = 0;
        while (true)
        {
            var port = FreeTcpPort();
            _listener.Prefixes.Clear();
            _listener.Prefixes.Add($"http://127.0.0.1:{port}/");
            try
            {
                _listener.Start();
                Endpoint = $"http://127.0.0.1:{port}";
                break;
            }
            catch (HttpListenerException) when (attempts++ < 5)
            {
                // The probed port was taken between probe and bind; retry.
            }
        }
        _pump = Task.Run(PumpAsync);
    }

    /// <summary>Base endpoint to hand to the config, e.g. http://127.0.0.1:49152.</summary>
    public string Endpoint { get; }

    public IReadOnlyCollection<CapturedOtlpRequest> Requests => _requests.ToArray();

    /// <summary>Requests whose path ends with the given suffix, e.g. "/v1/traces".</summary>
    public CapturedOtlpRequest[] RequestsTo(string pathSuffix) =>
        _requests.Where(r => r.Path.EndsWith(pathSuffix, StringComparison.Ordinal)).ToArray();

    /// <summary>
    /// Wait until a request matching <paramref name="pathSuffix"/> arrives.
    /// </summary>
    public CapturedOtlpRequest? WaitFor(string pathSuffix, TimeSpan timeout)
    {
        var deadline = DateTimeOffset.UtcNow + timeout;
        while (DateTimeOffset.UtcNow < deadline)
        {
            var hit = RequestsTo(pathSuffix).FirstOrDefault();
            if (hit is not null) return hit;
            Thread.Sleep(20);
        }
        return RequestsTo(pathSuffix).FirstOrDefault();
    }

    private static int FreeTcpPort()
    {
        var probe = new System.Net.Sockets.TcpListener(IPAddress.Loopback, 0);
        probe.Start();
        var port = ((IPEndPoint)probe.LocalEndpoint).Port;
        probe.Stop();
        return port;
    }

    private async Task PumpAsync()
    {
        while (!_stop.IsCancellationRequested)
        {
            HttpListenerContext ctx;
            try
            {
                ctx = await _listener.GetContextAsync().ConfigureAwait(false);
            }
            catch (Exception) when (_stop.IsCancellationRequested || !_listener.IsListening)
            {
                return;
            }

            using var body = new MemoryStream();
            await ctx.Request.InputStream.CopyToAsync(body).ConfigureAwait(false);
            var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (var key in ctx.Request.Headers.AllKeys)
            {
                if (key is not null) headers[key] = ctx.Request.Headers[key] ?? "";
            }
            _requests.Enqueue(new CapturedOtlpRequest(
                ctx.Request.Url?.AbsolutePath ?? "", headers, body.ToArray()));

            // 200 with an empty body is a valid OTLP export success response.
            ctx.Response.StatusCode = 200;
            ctx.Response.ContentType = "application/x-protobuf";
            ctx.Response.Close();
        }
    }

    public void Dispose()
    {
        _stop.Cancel();
        try { _listener.Stop(); } catch (ObjectDisposedException) { /* already down */ }
        try { _pump.Wait(TimeSpan.FromSeconds(2)); } catch (AggregateException) { /* pump ended on stop */ }
        _listener.Close();
    }
}
