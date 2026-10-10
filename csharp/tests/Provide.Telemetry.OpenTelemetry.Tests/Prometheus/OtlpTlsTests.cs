// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Net.Security;

using OpenTelemetry.Exporter;
using Provide.Telemetry;
using Provide.Telemetry.OpenTelemetry.Prometheus;
using Xunit;

namespace Provide.Telemetry.OpenTelemetry.Tests.Prometheus;

/// <summary>
/// Push security: the OTLP exporters trust a private CA and present a client
/// certificate, checked against the TLS listener as the server.
/// </summary>
[Collection("OpenTelemetry")]
public sealed class OtlpTlsTests : ListenerTestBase
{
    [Fact]
    public void Load_NothingConfiguredIsNull() => Assert.Null(OtlpTls.Load("", "", ""));

    [Theory]
    [InlineData(true, false)]
    [InlineData(false, true)]
    public void Load_CertificateAndKeyGoTogether(bool cert, bool key)
    {
        var error = Assert.Throws<ConfigurationError>(
            () => OtlpTls.Load("", cert ? Pki.ClientCert : "", key ? Pki.ClientKey : ""));
        Assert.Equal("OTLP client certificate and client key must be set together", error.Message);
    }

    [Fact]
    public void Load_UnreadableFilesAreConfigurationErrors()
    {
        var missing = Path.Combine(Pki.Dir, "missing.pem");
        Assert.StartsWith("OTLP TLS files: ", Assert.Throws<ConfigurationError>(() => OtlpTls.Load(missing, "", "")).Message);
        Assert.StartsWith("OTLP TLS files: ",
            Assert.Throws<ConfigurationError>(() => OtlpTls.Load("", Pki.ClientCert, missing)).Message);
        Pki.Write("empty.pem", "");
        Assert.Contains("holds no certificate",
            Assert.Throws<ConfigurationError>(() => OtlpTls.Load(Path.Combine(Pki.Dir, "empty.pem"), "", "")).Message);
    }

    [Fact]
    public void Load_ReadsTheCaAndTheClientPair()
    {
        var tls = OtlpTls.Load(Pki.CaFile, Pki.ClientCert, Pki.ClientKey)!;
        Assert.Single(tls.Roots!);
        Assert.True(tls.ClientCertificate!.HasPrivateKey);
        var caOnly = OtlpTls.Load(Pki.CaFile, "", "")!;
        Assert.Null(caOnly.ClientCertificate);
    }

    [Fact]
    public void Validate_ChainsToTheRootsAndKeepsOtherErrors()
    {
        using var server = System.Security.Cryptography.X509Certificates.X509Certificate2.CreateFromPemFile(Pki.CertFile, Pki.KeyFile);
        Assert.True(OtlpTls.Validate(server, SslPolicyErrors.RemoteCertificateChainErrors, Pki.Roots()));
        Assert.True(OtlpTls.Validate(server, SslPolicyErrors.None, Pki.Roots()));
        Assert.False(OtlpTls.Validate(server, SslPolicyErrors.RemoteCertificateNameMismatch, Pki.Roots()));
        Assert.False(OtlpTls.Validate(null, SslPolicyErrors.None, Pki.Roots()));
        using var stranger = new TestPki();
        Assert.False(OtlpTls.Validate(server, SslPolicyErrors.RemoteCertificateChainErrors, stranger.Roots()));
    }

    [Fact]
    public async Task CreateClient_TrustsThePrivateCaAndPresentsTheClientCertificate()
    {
        Start(p => p.WebConfig = WriteConfig(new Dictionary<object, object?>
        {
            ["tls_server_config"] = new Dictionary<object, object?>
            {
                ["cert_file"] = "{cert}",
                ["key_file"] = "{key}",
                ["client_ca_file"] = "{ca}",
            },
        }));
        using (var client = OtlpTls.Load(Pki.CaFile, Pki.ClientCert, Pki.ClientKey)!.CreateClient(TimeSpan.FromSeconds(7)))
        {
            Assert.Equal(TimeSpan.FromSeconds(7), client.Timeout);
            using var response = await client.GetAsync(Url("https"));
            Assert.Equal(200, (int)response.StatusCode);
        }
        using (var noClientCert = OtlpTls.Load(Pki.CaFile, "", "")!.CreateClient(TimeSpan.FromSeconds(5)))
        {
            await Assert.ThrowsAnyAsync<HttpRequestException>(() => noClientCert.GetAsync(Url("https")));
        }
        using var stranger = new TestPki();
        using var wrongCa = OtlpTls.Load(stranger.CaFile, Pki.ClientCert, Pki.ClientKey)!.CreateClient(TimeSpan.FromSeconds(5));
        await Assert.ThrowsAnyAsync<HttpRequestException>(() => wrongCa.GetAsync(Url("https")));
    }

    [Fact]
    public void Apply_InstallsTheClientFactoryOnlyWithTls()
    {
        var options = new OtlpExporterOptions();
        Endpoints.Apply(options, "https://collector:4318", "metrics", new Dictionary<string, string>());
        var defaultFactory = options.HttpClientFactory;
        Endpoints.Apply(options, "https://collector:4318", "metrics", new Dictionary<string, string>(),
            OtlpTls.Load(Pki.CaFile, "", ""));
        Assert.NotSame(defaultFactory, options.HttpClientFactory);
        options.TimeoutMilliseconds = 1234;
        using var client = options.HttpClientFactory();
        Assert.Equal(TimeSpan.FromMilliseconds(1234), client.Timeout);
    }

    // ── a TLS file that cannot be read leaves that signal uninstalled ────────

    private TelemetryConfig BadTls(string signal, bool failOpen)
    {
        var config = TelemetryConfig.Default();
        config.Tracing.Enabled = signal == "traces";
        config.Logging.OtlpEnabled = signal == "logs";
        config.Metrics.Enabled = signal == "metrics";
        var missing = Path.Combine(Pki.Dir, "missing.pem");
        switch (signal)
        {
            case "logs":
                config.Logging.OtlpEndpoint = "http://127.0.0.1:9";
                config.Logging.OtlpCertificate = missing;
                config.Exporter.LogsFailOpen = failOpen;
                break;
            case "traces":
                config.Tracing.OtlpEndpoint = "http://127.0.0.1:9";
                config.Tracing.OtlpCertificate = missing;
                config.Exporter.TracesFailOpen = failOpen;
                break;
            default:
                config.Metrics.OtlpEndpoint = "http://127.0.0.1:9";
                config.Metrics.OtlpCertificate = missing;
                config.Metrics.Exporters = ["otlp", "prometheus"];
                config.Exporter.MetricsFailOpen = failOpen;
                break;
        }
        return config;
    }

    [Theory]
    [InlineData("logs")]
    [InlineData("traces")]
    [InlineData("metrics")]
    public void UnreadableTls_IsTheSetupErrorAndTheSignalFallsBack(string signal)
    {
        ProvideTelemetry.SetupTelemetry(BadTls(signal, failOpen: true));
        Assert.StartsWith($"{signal} exporter: OTLP TLS files: ", ProvideTelemetry.GetHealthSnapshot().SetupError);
        var providers = ProvideTelemetry.GetRuntimeStatus().Providers;
        Assert.False(providers.Logs || providers.Traces || providers.Metrics);
        if (signal == "metrics") Assert.Equal(PrometheusEndpoint.SetupFailed, PrometheusEndpoint.Status);
    }

    [Theory]
    [InlineData("logs")]
    [InlineData("traces")]
    [InlineData("metrics")]
    public void UnreadableTls_RaisesWhenNotFailOpen(string signal) =>
        Assert.Throws<ConfigurationError>(() => ProvideTelemetry.SetupTelemetry(BadTls(signal, failOpen: false)));

    [Fact]
    public void Configure_JoinsEveryFailure()
    {
        var config = BadTls("logs", failOpen: true);
        config.Tracing.Enabled = true;
        config.Tracing.OtlpEndpoint = "http://127.0.0.1:9";
        config.Tracing.OtlpCertificate = config.Logging.OtlpCertificate;
        ProvideTelemetry.SetupTelemetry(config);
        var error = ProvideTelemetry.GetHealthSnapshot().SetupError;
        Assert.StartsWith("traces exporter: ", error);
        Assert.Contains("; logs exporter: ", error);
        using var backend = new OpenTelemetryBackend(TelemetryConfig.Default());
        Assert.Throws<ArgumentNullException>(() => backend.Configure(null!));
    }
}
