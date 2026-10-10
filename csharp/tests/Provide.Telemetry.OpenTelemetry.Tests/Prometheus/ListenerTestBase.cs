// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Net;
using System.Net.Http.Headers;
using System.Net.Security;
using System.Security.Cryptography.X509Certificates;
using System.Text;

using Provide.Telemetry;
using Provide.Telemetry.OpenTelemetry.Prometheus;
using YamlDotNet.Serialization;

namespace Provide.Telemetry.OpenTelemetry.Tests.Prometheus;

/// <summary>Shared plumbing for the listener tests: configs, web config files and an HTTP client.</summary>
public abstract class ListenerTestBase : PromTestBase
{
    internal const string Password = "e2e-test-only-password";
    private static readonly Lazy<string> Hash = new(() => BCrypt.Net.BCrypt.HashPassword(Password, 4));

    internal TestPki Pki { get; } = new();

    protected ListenerTestBase() => MarkReady();

    protected static void MarkReady() =>
        PrometheusEndpoint.MarkReady(new PrometheusPullReader(), new RenderOptions("UnderscoreEscapingWithSuffixes"));

    protected static TelemetryConfig ListenerConfig(Action<PrometheusConfig>? edit = null)
    {
        var config = PromConfig();
        config.Metrics.Prometheus.Listen = "true";
        config.Metrics.Prometheus.Port = 0;
        edit?.Invoke(config.Metrics.Prometheus);
        return config;
    }

    protected static string Start(Action<PrometheusConfig>? edit = null) => PrometheusListener.Sync(ListenerConfig(edit));

    /// <summary>Write a web config, replacing the fixture placeholders with real files and a real hash.</summary>
    internal string WriteConfig(object webConfig, string name = "web.yml")
    {
        var yaml = new SerializerBuilder().Build().Serialize(Substitute(webConfig));
        return Pki.Write(name, yaml);
    }

    private object? Substitute(object? node) => node switch
    {
        Dictionary<object, object?> map => map.ToDictionary(kv => kv.Key, kv => Substitute(kv.Value)),
        "{cert}" => Pki.CertFile,
        "{key}" => Pki.KeyFile,
        "{ca}" => Pki.CaFile,
        "{missing}" => Path.Combine(Pki.Dir, "missing.pem"),
        "bcrypt_of_e2e_test_only_password" => Hash.Value,
        _ => node,
    };

    protected static string Url(string scheme = "http", string path = "/metrics") =>
        $"{scheme}://127.0.0.1:{PrometheusListener.Address!.Port}{path}";

    /// <summary>Fetch a URL; returns the status, or throws for a transport (TLS) failure.</summary>
    internal async Task<HttpResponseMessage> Send(
        string url, bool trust = true, X509Certificate2? clientCert = null, bool auth = false,
        string method = "GET", string? authorization = null)
    {
        var handler = new SocketsHttpHandler { UseProxy = false };
        handler.SslOptions.RemoteCertificateValidationCallback = (_, certificate, _, errors) =>
            trust && OtlpTls.Validate(certificate as X509Certificate2, errors, Pki.Roots());
        if (clientCert is not null) handler.SslOptions.ClientCertificates = [clientCert];
        using var client = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(10) };
        using var request = new HttpRequestMessage(new HttpMethod(method), url);
        if (auth)
        {
            request.Headers.Authorization = new AuthenticationHeaderValue(
                "Basic", Convert.ToBase64String(Encoding.UTF8.GetBytes($"e2e:{Password}")));
        }
        if (authorization is not null) request.Headers.TryAddWithoutValidation("Authorization", authorization);
        return await client.SendAsync(request);
    }

    internal async Task<int> Status(
        string url, bool trust = true, X509Certificate2? clientCert = null, bool auth = false, string method = "GET")
    {
        using var response = await Send(url, trust, clientCert, auth, method);
        return (int)response.StatusCode;
    }

    protected override void Cleanup() => Pki.Dispose();
}
