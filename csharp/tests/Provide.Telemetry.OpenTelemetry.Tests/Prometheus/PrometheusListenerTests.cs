// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Net;
using System.Net.Sockets;
using System.Text;

using Provide.Telemetry;
using Provide.Telemetry.OpenTelemetry.Prometheus;
using Xunit;

namespace Provide.Telemetry.OpenTelemetry.Tests.Prometheus;

/// <summary>The standalone listener: the shared web config cases, requests and lifecycle.</summary>
[Collection("OpenTelemetry")]
public sealed class PrometheusListenerTests : ListenerTestBase
{
    public static IEnumerable<object[]> WebConfigCases() => PromFixtures.Rows("listener_web_config");

    [Theory]
    [MemberData(nameof(WebConfigCases))]
    public async Task WebConfig_FixtureCase(string id, Dictionary<object, object?> c)
    {
        var path = "";
        if (c.Str("web_config_path") is { } raw) path = raw.Replace("{missing}", Path.Combine(Pki.Dir, "missing.yml"));
        else if (c.Map("web_config") is { } webConfig) path = WriteConfig(webConfig);
        var error = Start(p => p.WebConfig = path);

        Assert.True(c.Flag("listener") == (PrometheusListener.Address is not null), id);
        if (c.Flag("error"))
        {
            Assert.StartsWith("prometheus listener: ", error);
            Assert.Equal("metrics.prometheus_listener.failed", Assert.Single(Warnings).Message);
            return;
        }
        Assert.Equal("", error);
        Assert.Equal(c.Flag("warning"), Warnings.Any(w => w.Message == "metrics.prometheus_listener.cleartext_auth"));
        var https = c.Str("scheme") == "https";
        var url = Url(c.Str("scheme")!);
        var clientCertRequired = c.Flag("client_cert_required");
        if (clientCertRequired) await Assert.ThrowsAnyAsync<HttpRequestException>(() => Status(url));
        var clientCert = clientCertRequired ? Pki.ClientCertificate() : null;
        if (c.Flag("auth")) Assert.Equal(401, await Status(url, clientCert: clientCert));
        Assert.Equal(200, await Status(url, clientCert: clientCert, auth: c.Flag("auth")));
        if (https) await Assert.ThrowsAnyAsync<HttpRequestException>(() => Status(url, trust: false, clientCert: clientCert));
    }

    [Fact]
    public async Task Requests_PathsMethodsAndQueryStrings()
    {
        Assert.Equal("", Start(p => p.Path = "/internal/metrics"));
        Assert.Equal(200, await Status(Url(path: "/internal/metrics")));
        Assert.Equal(200, await Status(Url(path: "/internal/metrics?debug=1")));
        Assert.Equal(404, await Status(Url(path: "/metrics")));
        Assert.Equal(404, await Status(Url(path: "/internal/metrics/x")));
        Assert.Equal(200, await Status(Url(path: "/internal/metrics"), method: "HEAD"));
        foreach (var method in new[] { "POST", "PUT", "DELETE" })
        {
            Assert.Equal(405, await Status(Url(path: "/internal/metrics"), method: method));
        }
        using var notFound = await Send(Url(path: "/nope"));
        Assert.Equal("text/plain; charset=utf-8", notFound.Content.Headers.ContentType!.ToString());
        Assert.Equal("not found\n", await notFound.Content.ReadAsStringAsync());
        using var ok = await Send(Url(path: "/internal/metrics"));
        Assert.Contains("provide_telemetry_setup_error", await ok.Content.ReadAsStringAsync());
        Assert.Equal(PrometheusRender.ContentTypeText, ok.Content.Headers.ContentType!.ToString());
    }

    [Fact]
    public async Task Requests_NotReadyIsServedAs503()
    {
        PrometheusEndpoint.ResetForTests();
        Start();
        using var response = await Send(Url());
        Assert.Equal(503, (int)response.StatusCode);
        Assert.Equal(PrometheusEndpoint.Reasons[PrometheusEndpoint.NotSetUp] + "\n", await response.Content.ReadAsStringAsync());
    }

    [Fact]
    public async Task BasicAuth_RejectsEveryMalformedOrWrongCredential()
    {
        Start(p => p.WebConfig = WriteConfig(new Dictionary<object, object?>
        {
            ["basic_auth_users"] = new Dictionary<object, object?> { ["e2e"] = "bcrypt_of_e2e_test_only_password" },
        }));
        string B64(string text) => Convert.ToBase64String(Encoding.UTF8.GetBytes(text));
        foreach (var header in new[]
                 {
                     "Bearer " + B64($"e2e:{Password}"), "Basic", "Basic !!!", "Basic " + B64("no-colon"),
                     "Basic " + B64("e2e:wrong"), "Basic " + B64($"other:{Password}"),
                     "Basic " + Convert.ToBase64String([0xff, 0xfe, 0x3a]),
                 })
        {
            using var response = await Send(Url(), authorization: header);
            Assert.True(401 == (int)response.StatusCode, header);
            Assert.Equal("Basic", response.Headers.WwwAuthenticate.ToString());
            Assert.Equal("text/plain; charset=utf-8", response.Content.Headers.ContentType!.ToString());
            Assert.Equal("unauthorized\n", await response.Content.ReadAsStringAsync());
        }
        using var lower = await Send(Url(), authorization: "basic " + B64($"e2e:{Password}"));
        Assert.Equal(200, (int)lower.StatusCode);
        Assert.Equal(200, await Status(Url(), auth: true)); // served from the verification cache
    }

    [Fact]
    public async Task Tls_AFailedHandshakeDoesNotStopTheListener()
    {
        Start(p => p.WebConfig = WriteConfig(TlsOnly()));
        using (var raw = new TcpClient())
        {
            await raw.ConnectAsync(IPAddress.Loopback, PrometheusListener.Address!.Port);
            var stream = raw.GetStream();
            await stream.WriteAsync("GET /metrics HTTP/1.1\r\n\r\n"u8.ToArray());
            try { _ = await Answered(token => stream.ReadAsync(new byte[1024], token).AsTask()); }
            catch (IOException) { /* the server drops the failed handshake */ }
        }
        Assert.Equal(200, await Status(Url("https")));
    }

    private static Dictionary<object, object?> TlsOnly(Dictionary<object, object?>? extra = null)
    {
        var tls = new Dictionary<object, object?> { ["cert_file"] = "{cert}", ["key_file"] = "{key}" };
        foreach (var (k, v) in extra ?? []) tls[k] = v;
        return new Dictionary<object, object?> { ["tls_server_config"] = tls };
    }

    [Fact]
    public async Task Tls_CertificatesAreReloadedWhenTheyChange()
    {
        Start(p => p.WebConfig = WriteConfig(TlsOnly()));
        Assert.Equal(200, await Status(Url("https")));
        var before = new TestPki();
        try
        {
            // Rotate to a pair from another CA: the old trust anchor no longer validates.
            File.Copy(before.CertFile, Pki.CertFile, overwrite: true);
            File.Copy(before.KeyFile, Pki.KeyFile, overwrite: true);
            File.SetLastWriteTimeUtc(Pki.CertFile, DateTime.UtcNow.AddMinutes(1));
            await Assert.ThrowsAnyAsync<HttpRequestException>(() => Status(Url("https")));
        }
        finally
        {
            before.Dispose();
        }
    }

    [Fact]
    public async Task Tls_AMissingFileAfterStartupFailsTheConnectionNotTheListener()
    {
        Start(p => p.WebConfig = WriteConfig(TlsOnly()));
        var saved = File.ReadAllText(Pki.KeyFile);
        File.Delete(Pki.KeyFile);
        await Assert.ThrowsAnyAsync<HttpRequestException>(() => Status(Url("https")));
        File.Delete(Pki.CertFile);
        await Assert.ThrowsAnyAsync<HttpRequestException>(() => Status(Url("https")));
        Assert.NotNull(PrometheusListener.Address);
        _ = saved;
    }

    [Fact]
    public async Task Tls_ClientCertificateIsOptionalWithVerifyClientCertIfGiven()
    {
        Start(p => p.WebConfig = WriteConfig(TlsOnly(new()
        {
            ["client_ca_file"] = "{ca}",
            ["client_auth_type"] = "VerifyClientCertIfGiven",
            ["min_version"] = "TLS13",
        })));
        Assert.Equal(200, await Status(Url("https")));
        Assert.Equal(200, await Status(Url("https"), clientCert: Pki.ClientCertificate()));
        using var stranger = new TestPki();
        await Assert.ThrowsAnyAsync<HttpRequestException>(
            () => Status(Url("https"), clientCert: stranger.ClientCertificate()));
    }

    [Fact]
    public void Tls_NoClientCertAcceptsAnOfferedCertificateUnchecked()
    {
        var tls = new TlsReloader(Pki.CertFile, Pki.KeyFile, null, WebConfigLoader.NoClientCert,
            System.Security.Authentication.SslProtocols.Tls12);
        using var stranger = new TestPki();
        using var cert = stranger.ClientCertificate();
        Assert.True(tls.VerifyClient(cert));
        Assert.True(tls.VerifyClient(null));
        var options = tls.Options();
        Assert.False(options.ClientCertificateRequired);
        Assert.Same(tls.Certificate(), options.ServerCertificateSelectionCallback!(null!, null));
    }

    // ── lifecycle ────────────────────────────────────────────────────────────

    [Fact]
    public void Lifecycle_KeepsRestartsAndStops()
    {
        Assert.Equal("", Start());
        var first = PrometheusListener.Current;
        var firstPort = PrometheusListener.Address!.Port;
        Assert.Equal("", Start());
        Assert.Same(first, PrometheusListener.Current);
        Assert.Equal("", Start(p => p.Path = "/other"));
        Assert.NotSame(first, PrometheusListener.Current);
        Assert.False(Accepts(firstPort), "the replaced listener still accepts");
        var secondPort = PrometheusListener.Address!.Port;
        Assert.True(Accepts(secondPort));
        Assert.Equal("", PrometheusListener.Sync(PromConfig()));
        Assert.Null(PrometheusListener.Address);
        Assert.False(Accepts(secondPort), "a stopped listener still accepts");
        PrometheusListener.Stop(); // stopping twice is a no-op
    }

    private static bool Accepts(int port)
    {
        using var client = new TcpClient();
        try
        {
            client.Connect(IPAddress.Loopback, port);
            return true;
        }
        catch (SocketException)
        {
            return false;
        }
    }

    [Fact]
    public void Lifecycle_ABindFailureIsReported()
    {
        using var busy = new TcpListener(IPAddress.Loopback, 0);
        busy.Start();
        var error = Start(p => p.Port = ((IPEndPoint)busy.LocalEndpoint).Port);
        Assert.Null(PrometheusListener.Address);
        Assert.StartsWith("prometheus listener: ", error);
        var warning = Assert.Single(Warnings);
        Assert.Equal("metrics.prometheus_listener.failed", warning.Message);
        Assert.Equal(error["prometheus listener: ".Length..], warning.Fields["error"]);
    }

    [Fact]
    public async Task Lifecycle_Ipv6Loopback()
    {
        if (!Socket.OSSupportsIPv6) return;
        var error = Start(p => p.Host = "::1");
        if (error.Length > 0) return; // no IPv6 loopback on this host
        Assert.Equal(AddressFamily.InterNetworkV6, PrometheusListener.Address!.AddressFamily);
        Assert.Equal(200, await Status($"http://[::1]:{PrometheusListener.Address.Port}/metrics"));
    }

    [Theory]
    [InlineData("localhost", true)]
    [InlineData("127.0.0.1", true)]
    [InlineData("127.0.0.2", true)]
    [InlineData("::1", true)]
    [InlineData("0.0.0.0", false)]
    [InlineData("example.com", false)]
    public void IsLoopback(string host, bool want) => Assert.Equal(want, PrometheusListener.IsLoopback(host));

    [Fact]
    public void Resolve_PrefersIpv4ForAName()
    {
        Assert.Equal(IPAddress.Parse("::1"), PrometheusListener.Resolve("::1"));
        Assert.Equal(AddressFamily.InterNetwork, PrometheusListener.Resolve("localhost").AddressFamily);
        Assert.Throws<SocketException>(() => PrometheusListener.Resolve("no-such-host.invalid"));
        Assert.StartsWith("prometheus listener: ", Start(p => p.Host = "no-such-host.invalid"));
    }

    [Fact]
    public void ExposureWarnings()
    {
        PrometheusListener.WarnExposure("0.0.0.0", new WebSecurity(new Dictionary<string, string> { ["u"] = "h" }));
        PrometheusListener.WarnExposure("127.0.0.1", new WebSecurity());
        Assert.Equal(
            ["metrics.prometheus_listener.exposed", "metrics.prometheus_listener.cleartext_auth"],
            Warnings.Select(w => w.Message));
        Assert.Equal("0.0.0.0", Warnings[0].Fields["host"]);
        Assert.Empty(Warnings[1].Fields);
    }

    [Fact]
    public void DefaultWarn_GoesThroughTheSdkLogger()
    {
        var config = PromConfig();
        config.Logging.Format = "json";
        ProvideTelemetry.SetupTelemetry(config);
        var stderr = StderrOf(() => SdkWarnings.DefaultWarn(
            "metrics.prometheus_listener.exposed", new Dictionary<string, object?> { ["host"] = "0.0.0.0" }));
        Assert.Contains("metrics.prometheus_listener.exposed", stderr);
        Assert.Contains("\"logger_name\":\"provide.telemetry.otel\"", stderr);
        Assert.Contains("\"host\":\"0.0.0.0\"", stderr);
    }

    [Fact]
    public async Task Setup_ShutdownAndReconfigureDriveTheListener()
    {
        PrometheusEndpoint.ResetForTests();
        ProvideTelemetry.SetupTelemetry(ListenerConfig());
        Assert.NotNull(PrometheusListener.Address);
        Assert.Equal("", ProvideTelemetry.GetHealthSnapshot().SetupError);
        ProvideTelemetry.Counter("listener.hits").Add(2);
        using (var response = await Send(Url()))
        {
            Assert.Contains("listener_hits_total 2\n", await response.Content.ReadAsStringAsync());
        }
        var first = PrometheusListener.Current;
        ProvideTelemetry.ReconfigureTelemetry(ListenerConfig(p => p.Path = "/moved"));
        Assert.NotSame(first, PrometheusListener.Current);
        Assert.Equal(200, await Status(Url(path: "/moved")));

        ProvideTelemetry.ShutdownTelemetry();
        Assert.Null(PrometheusListener.Address);
        Assert.Equal(PrometheusEndpoint.ShutDown, PrometheusEndpoint.Status);
    }

    [Fact]
    public void Setup_AListenerThatCannotStartIsTheSetupErrorAndNeverFailsSetup()
    {
        using var busy = new TcpListener(IPAddress.Loopback, 0);
        busy.Start();
        var port = ((IPEndPoint)busy.LocalEndpoint).Port;
        ProvideTelemetry.SetupTelemetry(ListenerConfig(p => p.Port = port));
        var error = ProvideTelemetry.GetHealthSnapshot().SetupError;
        Assert.StartsWith("prometheus listener: ", error);
        Assert.Equal(error, ProvideTelemetry.GetRuntimeStatus().SetupError);
        Assert.Contains("provide_telemetry_setup_error 1\n", Scrape());

        // Reconfiguring onto a free port starts it and clears the error.
        ProvideTelemetry.ReconfigureTelemetry(ListenerConfig());
        Assert.NotNull(PrometheusListener.Address);
        Assert.Equal("", ProvideTelemetry.GetHealthSnapshot().SetupError);
    }

    [Fact]
    public void Setup_TheEnvironmentPathStartsItToo()
    {
        SetEnv("OTEL_METRICS_EXPORTER", "prometheus");
        SetEnv("PROVIDE_METRICS_PROMETHEUS_LISTEN", "auto");
        SetEnv("OTEL_EXPORTER_PROMETHEUS_PORT", "0");
        SetEnv("PROVIDE_TRACE_ENABLED", "false");
        ProvideTelemetry.SetupTelemetry();
        Assert.NotNull(PrometheusListener.Address);
        SetEnv("PROVIDE_METRICS_PROMETHEUS_PATH", "/env");
        var first = PrometheusListener.Current;
        ProvideTelemetry.ReloadRuntimeFromEnv();
        Assert.NotSame(first, PrometheusListener.Current);
    }

    [Fact]
    public void Setup_ALazyStartFollowsTheEnvironment()
    {
        SetEnv("OTEL_METRICS_EXPORTER", "prometheus");
        SetEnv("PROVIDE_METRICS_PROMETHEUS_LISTEN", "true");
        SetEnv("OTEL_EXPORTER_PROMETHEUS_PORT", "0");
        ProvideTelemetry.Counter("lazy").Add(1);
        Assert.NotNull(PrometheusListener.Address);
    }

    [Fact]
    public void Setup_ExplicitConfigIsValidated()
    {
        var config = ListenerConfig(p => p.Path = "metrics");
        Assert.Throws<ConfigurationError>(() => ProvideTelemetry.SetupTelemetry(config));
        ProvideTelemetry.SetupTelemetry(PromConfig());
        Assert.Throws<ConfigurationError>(() => ProvideTelemetry.ReconfigureTelemetry(config));
    }
}
