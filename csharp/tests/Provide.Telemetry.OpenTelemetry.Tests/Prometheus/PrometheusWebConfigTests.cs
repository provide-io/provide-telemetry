// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Net;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Text;

using Provide.Telemetry.OpenTelemetry.Prometheus;
using Xunit;

namespace Provide.Telemetry.OpenTelemetry.Tests.Prometheus;

/// <summary>Web config validation (fail closed), the request parser and the read timeout.</summary>
[Collection("OpenTelemetry")]
public sealed class PrometheusWebConfigTests : ListenerTestBase
{
    private static Dictionary<object, object?> Tls(params (string Key, object? Value)[] entries)
    {
        var tls = new Dictionary<object, object?> { ["cert_file"] = "{cert}", ["key_file"] = "{key}" };
        foreach (var (k, v) in entries) tls[k] = v;
        return new Dictionary<object, object?> { ["tls_server_config"] = tls };
    }

    public static IEnumerable<object[]> Rejections() =>
    [
        [new Dictionary<object, object?> { ["http_server_config"] = new Dictionary<object, object?>() }, "only [basic_auth_users, tls_server_config] are supported"],
        [new Dictionary<object, object?> { ["basic_auth_users"] = "e2e" }, "basic_auth_users must map user names to bcrypt hashes"],
        [new Dictionary<object, object?> { ["basic_auth_users"] = new Dictionary<object, object?> { ["u"] = "plain" } }, "basic_auth_users[u] is not a bcrypt hash"],
        [new Dictionary<object, object?> { ["basic_auth_users"] = new Dictionary<object, object?> { ["u"] = null } }, "basic_auth_users[u] is not a bcrypt hash"],
        [new Dictionary<object, object?> { ["tls_server_config"] = "x" }, "tls_server_config: only [cert_file"],
        [Tls(("cipher_suites", new List<object?>())), "tls_server_config: only [cert_file"],
        [new Dictionary<object, object?> { ["basic_auth_users"] = null, ["http_server_config"] = null }, "only [basic_auth_users, tls_server_config] are supported"],
        [new Dictionary<object, object?> { ["tls_server_config"] = new Dictionary<object, object?> { ["cert_file"] = "{cert}" } }, "needs cert_file and key_file"],
        [new Dictionary<object, object?> { ["tls_server_config"] = new Dictionary<object, object?> { ["key_file"] = "{key}" } }, "needs cert_file and key_file"],
        [Tls(("min_version", "TLS10")), "tls_server_config.min_version 'TLS10': want TLS12 or TLS13"],
        [Tls(("client_auth_type", "Sometimes")), "tls_server_config.client_auth_type 'Sometimes' is not supported"],
        [Tls(("client_auth_type", "RequireAndVerifyClientCert")), "client_auth_type RequireAndVerifyClientCert needs client_ca_file"],
        [Tls(("client_auth_type", "VerifyClientCertIfGiven")), "client_auth_type VerifyClientCertIfGiven needs client_ca_file"],
        [Tls(("key_file", "{missing}")), "tls_server_config: "],
        [Tls(("cert_file", "{missing}")), "tls_server_config: "],
        [Tls(("client_ca_file", "{missing}")), "tls_server_config: "],
        [Tls(("key_file", "{cert}")), "tls_server_config: "],
    ];

    [Theory]
    [MemberData(nameof(Rejections))]
    public void Load_RejectsWithAReason(Dictionary<object, object?> webConfig, string reason)
    {
        var path = WriteConfig(webConfig);
        var error = Assert.Throws<WebConfigException>(() => WebConfigLoader.Load(path));
        Assert.Contains(reason, error.Message);
        Assert.StartsWith("prometheus listener: ", Start(p => p.WebConfig = path));
        Assert.Null(PrometheusListener.Address);
    }

    [Theory]
    [InlineData("- a\n- b\n")]
    [InlineData("just text\n")]
    [InlineData("[1: x]\n")]
    [InlineData("? [a]\n: b\n")]
    public void Load_RejectsANonMappingOrNonStringKeys(string yaml)
    {
        var error = Assert.Throws<WebConfigException>(() => WebConfigLoader.Load(Pki.Write("odd.yml", yaml)));
        Assert.Contains("only [basic_auth_users, tls_server_config] are supported", error.Message);
    }

    [Fact]
    public void Load_RejectsMalformedYamlAndUnreadableFiles()
    {
        Assert.Contains("web config ", Assert.Throws<WebConfigException>(
            () => WebConfigLoader.Load(Pki.Write("bad.yml", "a: [unclosed\n"))).Message);
        Assert.Contains("missing.yml", Assert.Throws<WebConfigException>(
            () => WebConfigLoader.Load(Path.Combine(Pki.Dir, "missing.yml"))).Message);
        Assert.Throws<WebConfigException>(() => WebConfigLoader.Load(Pki.Dir));
    }

    [Fact]
    public void Load_AnEmptyFileOrEmptySectionsMeanPlainHttp()
    {
        var empty = WebConfigLoader.Load(Pki.Write("empty.yml", ""));
        Assert.Null(empty.Tls);
        Assert.Empty(empty.Users);
        Assert.True(empty.Authorized(null));
        var nulls = WebConfigLoader.Load(Pki.Write("nulls.yml", "basic_auth_users:\n"));
        Assert.Empty(nulls.Users);
    }

    [Fact]
    public void Load_RelativePathsResolveAgainstTheConfigFile()
    {
        var security = WebConfigLoader.Load(Pki.Write("rel.yml",
            "tls_server_config:\n  cert_file: server.crt\n  key_file: server.key\n  client_ca_file: ca.crt\n"));
        var tls = security.Tls!;
        Assert.Equal(Pki.CertFile, tls.CertFile);
        Assert.Equal(Pki.KeyFile, tls.KeyFile);
        Assert.Equal(WebConfigLoader.RequireAndVerifyClientCert, tls.ClientAuth);
        Assert.Equal(SslProtocols.Tls12 | SslProtocols.Tls13, tls.Protocols);
        Assert.Single(tls.ClientRoots!);
        Assert.True(tls.Options().ClientCertificateRequired);
        Assert.False(tls.VerifyClient(null));
    }

    [Fact]
    public void Load_AnEmptyCaFileFailsClosed()
    {
        Pki.Write("empty-ca.crt", "");
        var error = Assert.Throws<WebConfigException>(() => WebConfigLoader.Load(WriteConfig(
            Tls(("client_ca_file", Path.Combine(Pki.Dir, "empty-ca.crt"))))));
        Assert.Contains("holds no certificate", error.Message);
    }

    [Fact]
    public void Authorized_InvalidUtf8IsRejectedNotReplaced()
    {
        var security = new WebSecurity(new Dictionary<string, string>
        {
            ["u"] = BCrypt.Net.BCrypt.HashPassword("\uFFFD", 4),
        });
        Assert.True(security.Authorized("Basic " + Convert.ToBase64String(Encoding.UTF8.GetBytes("u:\uFFFD"))));
        Assert.False(security.Authorized("Basic " + Convert.ToBase64String([(byte)'u', (byte)':', 0xff])));
    }

    [Fact]
    public void Authorized_AnEmptyUserNameAndAColonInThePassword()
    {
        var security = new WebSecurity(new Dictionary<string, string>
        {
            [""] = BCrypt.Net.BCrypt.HashPassword("a:b", 4),
        });
        Assert.True(security.Authorized("Basic " + Convert.ToBase64String(Encoding.UTF8.GetBytes(":a:b"))));
        Assert.False(security.Authorized(null));
    }

    [Fact]
    public void Authenticate_ChecksTheUsersOwnHashAndCachesSuccesses()
    {
        var users = new Dictionary<string, string> { ["u"] = BCrypt.Net.BCrypt.HashPassword("secret", 4) };
        var security = new WebSecurity(users);
        Assert.False(security.Authenticate("u", Password)); // the dummy hash's password is not u's
        Assert.True(security.Authenticate("u", "secret"));
        users.Clear();
        Assert.True(security.Authenticate("u", "secret")); // served from the cache
        Assert.False(security.Authenticate("u", "other"));
    }

    [Fact]
    public void Authenticate_CachesOnlySuccesses()
    {
        var security = new WebSecurity(new Dictionary<string, string>
        {
            ["e2e"] = BCrypt.Net.BCrypt.HashPassword(Password, 4),
        });
        Assert.False(security.Authenticate("e2e", "nope"));
        Assert.False(security.Authenticate("nobody", Password));
        Assert.True(security.Authenticate("e2e", Password));
        Assert.True(security.Authenticate("e2e", Password));
        Assert.False(security.Authenticate("e2e", Password + "x"));
    }

    // ── the request parser ───────────────────────────────────────────────────

    [Theory]
    [InlineData("GET /metrics HTTP/1.1", "GET", "/metrics")]
    [InlineData("HEAD /m?x=1#f HTTP/1.0", "HEAD", "/m")]
    [InlineData("GET /m#frag HTTP/1.1\r\nAccept: a\r\naccept: b", "GET", "/m")]
    public void Parse_RequestLineAndHeaders(string head, string method, string path)
    {
        var request = HttpRequestReader.Parse(head)!;
        Assert.Equal((method, path), (request.Method, request.Path));
        Assert.Equal(head.Contains("Accept") ? "a" : null, request.Header("ACCEPT"));
    }

    [Theory]
    [InlineData("GET /metrics")]
    [InlineData("GET /metrics HTTP/2.0")]
    [InlineData(" /metrics HTTP/1.1")]
    [InlineData("GET  /metrics HTTP/1.1")]
    [InlineData("GET /metrics HTTP/1.1\r\nno-colon")]
    [InlineData("GET /metrics HTTP/1.1\r\n: empty-name")]
    public void Parse_RejectsMalformedRequests(string head) => Assert.Null(HttpRequestReader.Parse(head));

    [Theory]
    [InlineData(200, "OK")]
    [InlineData(400, "Bad Request")]
    [InlineData(401, "Unauthorized")]
    [InlineData(404, "Not Found")]
    [InlineData(405, "Method Not Allowed")]
    [InlineData(503, "Service Unavailable")]
    public void Format_StatusLineHeadersAndBody(int status, string reason)
    {
        var bytes = HttpRequestReader.Format(new PrometheusResponse(status, [new("X-A", "1")], "hi"u8.ToArray()));
        Assert.Equal(
            $"HTTP/1.1 {status} {reason}\r\nX-A: 1\r\nContent-Length: 2\r\nConnection: close\r\n\r\nhi",
            Encoding.Latin1.GetString(bytes));
    }

    private static async Task<string> Raw(byte[] request, bool close = false)
    {
        using var client = new TcpClient();
        await client.ConnectAsync(IPAddress.Loopback, PrometheusListener.Address!.Port);
        var stream = client.GetStream();
        await stream.WriteAsync(request);
        if (close) client.Client.Shutdown(SocketShutdown.Send);
        using var reader = new StreamReader(stream, Encoding.Latin1);
        return await Answered(token => reader.ReadToEndAsync(token));
    }

    [Fact]
    public async Task Listener_AnswersMalformedOversizedAndTruncatedRequests()
    {
        Start();
        var bad = await Raw("BREW /metrics\r\n\r\n"u8.ToArray());
        Assert.StartsWith("HTTP/1.1 400 Bad Request\r\n", bad);
        Assert.EndsWith("\r\n\r\nbad request\n", bad);
        var huge = Encoding.ASCII.GetBytes("GET /metrics HTTP/1.1\r\nX: " + new string('a', PrometheusListener.MaxHeaderBytes) + "\r\n\r\n");
        Assert.StartsWith("HTTP/1.1 400 Bad Request\r\n", await Raw(huge));
        Assert.StartsWith("HTTP/1.1 400 Bad Request\r\n", await Raw("GET /metrics HTTP/1.1\r\n"u8.ToArray(), close: true));
        var split = await Raw("GET /metrics HTTP/1.1\r\nAccept: text/plain;escaping=allow-utf-8\r\n\r\n"u8.ToArray());
        Assert.StartsWith("HTTP/1.1 200 OK\r\n", split);
        Assert.Contains("Content-Type: " + PrometheusRender.ContentTypeUtf8 + "\r\n", split);
        Assert.Contains("Connection: close\r\n", split);
    }

    [Fact]
    public async Task Listener_DropsAClientThatSendsNothingWithinTheReadTimeout()
    {
        var saved = PrometheusListener.ReadTimeout;
        PrometheusListener.ReadTimeout = TimeSpan.FromMilliseconds(200);
        try
        {
            Start();
            using var client = new TcpClient();
            await client.ConnectAsync(IPAddress.Loopback, PrometheusListener.Address!.Port);
            var started = DateTime.UtcNow;
            var read = await Answered(token => client.GetStream().ReadAsync(new byte[16], token).AsTask());
            Assert.Equal(0, read);
            Assert.True(DateTime.UtcNow - started < TimeSpan.FromSeconds(5));

            // A blank line first is an empty request line: answered at once, not waited on.
            using var blank = new TcpClient();
            await blank.ConnectAsync(IPAddress.Loopback, PrometheusListener.Address!.Port);
            await blank.GetStream().WriteAsync("\r\n\r\n"u8.ToArray());
            using var reader = new StreamReader(blank.GetStream(), Encoding.Latin1);
            Assert.StartsWith("HTTP/1.1 400 Bad Request\r\n", await Answered(token => reader.ReadToEndAsync(token)));
            Assert.Equal(200, await Status(Url()));
        }
        finally
        {
            PrometheusListener.ReadTimeout = saved;
        }
    }
}
