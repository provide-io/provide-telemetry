// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Text;

using Provide.Telemetry;

namespace Provide.Telemetry.OpenTelemetry.Prometheus;

/// <summary>
/// The Tier 3 standalone Prometheus listener.
/// </summary>
/// <remarks>
/// Serves <see cref="PrometheusEndpoint.ResponseFor"/> at
/// <c>PROVIDE_METRICS_PROMETHEUS_PATH</c> on
/// <c>OTEL_EXPORTER_PROMETHEUS_HOST:PORT</c>, optionally secured by a
/// Prometheus web config (<see cref="WebConfigLoader"/>). It speaks just enough
/// HTTP/1.x for a scrape — a request line and headers, no body, one response
/// per connection — over a <see cref="TcpListener"/>, because
/// <c>HttpListener</c> cannot serve TLS on Linux. Failures are logged and
/// returned for the health snapshot's <c>setup_error</c>; they never fail setup.
/// </remarks>
internal static class PrometheusListener
{
    /// <summary>The budget for one exchange: TLS handshake, request headers and response.</summary>
    internal static TimeSpan ReadTimeout { get; set; } = TimeSpan.FromSeconds(10);

    internal const int MaxHeaderBytes = 16 * 1024;

    /// <summary>Where listener warnings go; tests swap it to capture them.</summary>
    internal static Action<string, IReadOnlyDictionary<string, object?>> Warn { get; set; } = DefaultWarn;

    private static readonly object Gate = new();
    private static Running? _running;

    internal static void DefaultWarn(string message, IReadOnlyDictionary<string, object?> fields) =>
        Logging.GetLogger("provide.telemetry.prometheus").Warning(message, fields);

    /// <summary>The settings that, when changed, restart the listener.</summary>
    internal readonly record struct ListenerKey(string Host, int Port, string Path, string WebConfig);

    /// <summary>
    /// Make the listener match <paramref name="config"/>: start, stop, restart
    /// on a changed key, or leave it. Returns a failure message, or "".
    /// </summary>
    public static string Sync(TelemetryConfig config)
    {
        lock (Gate)
        {
            if (!config.Metrics.PrometheusListenerEnabled())
            {
                StopLocked();
                return "";
            }
            var p = config.Metrics.Prometheus;
            var key = new ListenerKey(p.Host, p.Port, p.Path, p.WebConfig);
            if (_running is not null && _running.Key == key) return "";
            StopLocked();
            try
            {
                _running = Start(key);
                return "";
            }
            catch (Exception ex)
            {
                var error = $"prometheus listener: {ex.Message}";
                Warn("metrics.prometheus_listener.failed", Fields("error", ex.Message));
                return error;
            }
        }
    }

    /// <summary>Stop the listener; a no-op when none runs.</summary>
    public static void Stop()
    {
        lock (Gate)
        {
            StopLocked();
        }
    }

    /// <summary>The bound endpoint of the running listener, or null.</summary>
    public static IPEndPoint? Address
    {
        get { lock (Gate) { return _running?.Endpoint; } }
    }

    /// <summary>The running listener's key, or null; lets tests see a restart.</summary>
    internal static object? Current
    {
        get { lock (Gate) { return _running; } }
    }

    private static void StopLocked()
    {
        _running?.Dispose();
        _running = null;
    }

    private static Running Start(ListenerKey key)
    {
        var security = key.WebConfig.Length > 0 ? WebConfigLoader.Load(key.WebConfig) : new WebSecurity();
        var running = new Running(key, Resolve(key.Host), security);
        WarnExposure(key.Host, security);
        return running;
    }

    internal static IPAddress Resolve(string host)
    {
        if (IPAddress.TryParse(host, out var address)) return address;
        // A name binds its IPv4 address, as Python's listener does; an IPv6
        // listener is asked for by address.
        return Dns.GetHostAddresses(host, AddressFamily.InterNetwork)[0];
    }

    internal static void WarnExposure(string host, WebSecurity security)
    {
        if (!IsLoopback(host)) Warn("metrics.prometheus_listener.exposed", Fields("host", host));
        if (security.Users.Count > 0 && security.Tls is null)
        {
            Warn("metrics.prometheus_listener.cleartext_auth", Fields());
        }
    }

    internal static bool IsLoopback(string host) =>
        host == "localhost" || (IPAddress.TryParse(host, out var address) && IPAddress.IsLoopback(address));

    private static Dictionary<string, object?> Fields(params string[] pairs)
    {
        var fields = new Dictionary<string, object?>(StringComparer.Ordinal);
        for (var i = 0; i + 1 < pairs.Length; i += 2) fields[pairs[i]] = pairs[i + 1];
        return fields;
    }

    /// <summary>One bound listener and its accept loop.</summary>
    private sealed class Running : IDisposable
    {
        private readonly TcpListener _listener;
        private readonly CancellationTokenSource _stop = new();
        private readonly Task _accept;
        private readonly WebSecurity _security;

        public Running(ListenerKey key, IPAddress address, WebSecurity security)
        {
            Key = key;
            _security = security;
            _listener = new TcpListener(address, key.Port);
            _listener.Start();
            Endpoint = (IPEndPoint)_listener.LocalEndpoint;
            _accept = Task.Run(AcceptLoop);
        }

        public ListenerKey Key { get; }

        public IPEndPoint Endpoint { get; }

        private async Task AcceptLoop()
        {
            while (!_stop.IsCancellationRequested)
            {
                try
                {
                    var client = await _listener.AcceptTcpClientAsync(_stop.Token).ConfigureAwait(false);
                    _ = Task.Run(() => Serve(client));
                }
                catch (Exception)
                {
                    // Stopping cancels the pending accept; anything else is one
                    // failed accept (a client that reset first), and the loop
                    // condition decides whether to carry on.
                }
            }
        }

        private async Task Serve(TcpClient client)
        {
            using var _ = client;
            using var deadline = CancellationTokenSource.CreateLinkedTokenSource(_stop.Token);
            deadline.CancelAfter(ReadTimeout);
            try
            {
                Stream stream = client.GetStream();
                if (_security.Tls is { } tls)
                {
                    var ssl = new SslStream(stream, leaveInnerStreamOpen: false);
                    await ssl.AuthenticateAsServerAsync(tls.Options(), deadline.Token).ConfigureAwait(false);
                    stream = ssl;
                }
                await using (stream.ConfigureAwait(false))
                {
                    var request = await HttpRequestReader.ReadAsync(stream, deadline.Token).ConfigureAwait(false);
                    var response = Dispatch(request);
                    await stream.WriteAsync(HttpRequestReader.Format(response), deadline.Token).ConfigureAwait(false);
                }
            }
            catch (Exception)
            {
                // A failed handshake, a timeout or a dropped client ends this
                // connection only; the listener keeps serving.
            }
        }

        private PrometheusResponse Dispatch(HttpRequest? request)
        {
            if (request is null) return Plain(400, "bad request\n");
            if (request.Path != Key.Path) return Plain(404, "not found\n");
            if (!_security.Authorized(request.Header("Authorization")))
            {
                return new PrometheusResponse(
                    401,
                    [new("WWW-Authenticate", "Basic"), new("Content-Type", "text/plain; charset=utf-8")],
                    Encoding.UTF8.GetBytes("unauthorized\n"));
            }
            return PrometheusEndpoint.ResponseFor(request.Method, request.Header("Accept"));
        }

        private static PrometheusResponse Plain(int status, string body) =>
            new(status, [new("Content-Type", "text/plain; charset=utf-8")], Encoding.UTF8.GetBytes(body));

        public void Dispose()
        {
            _stop.Cancel();
            _listener.Stop();
            _accept.Wait(); // the loop swallows its own exceptions, so this only waits
            _stop.Dispose();
        }
    }
}

/// <summary>A parsed request line and headers.</summary>
internal sealed record HttpRequest(string Method, string Path, IReadOnlyDictionary<string, string> Headers)
{
    public string? Header(string name) => Headers.TryGetValue(name, out var value) ? value : null;
}

/// <summary>Just enough HTTP/1.x for a scrape.</summary>
internal static class HttpRequestReader
{
    private static readonly byte[] EndOfHeaders = "\r\n\r\n"u8.ToArray();

    /// <summary>Read a request line and headers, or return null when they are malformed or too large.</summary>
    public static async Task<HttpRequest?> ReadAsync(Stream stream, CancellationToken token)
    {
        var buffer = new byte[PrometheusListener.MaxHeaderBytes];
        var length = 0;
        while (buffer.AsSpan(0, length).IndexOf(EndOfHeaders) < 0)
        {
            if (length == buffer.Length) return null;
            var read = await stream.ReadAsync(buffer.AsMemory(length), token).ConfigureAwait(false);
            if (read == 0) return null;
            length += read;
        }
        return Parse(Encoding.Latin1.GetString(buffer, 0, buffer.AsSpan(0, length).IndexOf(EndOfHeaders)));
    }

    /// <summary>Parse the text before the blank line, or return null when it is malformed.</summary>
    internal static HttpRequest? Parse(string head)
    {
        var lines = head.Split("\r\n");
        var parts = lines[0].Split(' ');
        if (parts.Length != 3 || parts[0].Length == 0 || !parts[2].StartsWith("HTTP/1.", StringComparison.Ordinal))
        {
            return null;
        }
        var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var line in lines.Skip(1))
        {
            var colon = line.IndexOf(':');
            if (colon <= 0) return null;
            headers.TryAdd(line[..colon].Trim(), line[(colon + 1)..].Trim());
        }
        var target = parts[1];
        var end = target.IndexOfAny(['?', '#']);
        return new HttpRequest(parts[0], end < 0 ? target : target[..end], headers);
    }

    private static string Reason(int status) => status switch
    {
        200 => "OK",
        400 => "Bad Request",
        401 => "Unauthorized",
        404 => "Not Found",
        405 => "Method Not Allowed",
        _ => "Service Unavailable",
    };

    /// <summary>The response's bytes: status line, headers, Content-Length, Connection: close, body.</summary>
    public static byte[] Format(PrometheusResponse response)
    {
        var head = new StringBuilder($"HTTP/1.1 {response.Status} {Reason(response.Status)}\r\n");
        foreach (var (name, value) in response.Headers) head.Append(name).Append(": ").Append(value).Append("\r\n");
        head.Append("Content-Length: ").Append(response.Body.Length).Append("\r\n");
        head.Append("Connection: close\r\n\r\n");
        return [.. Encoding.Latin1.GetBytes(head.ToString()), .. response.Body];
    }
}
