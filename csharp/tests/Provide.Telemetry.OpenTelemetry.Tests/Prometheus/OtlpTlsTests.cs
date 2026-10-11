// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Net.Security;
using System.Security.Cryptography.X509Certificates;

using OpenTelemetry.Exporter;
using Provide.Telemetry;
using Provide.Telemetry.OpenTelemetry.Prometheus;
using Xunit;

namespace Provide.Telemetry.OpenTelemetry.Tests.Prometheus;

/// <summary>
/// Push security (<c>prometheus_metrics.push_security</c>): the OTLP exporters
/// trust a private CA and present a client certificate, checked against the TLS
/// listener as the server; a file that cannot be read or loaded leaves that
/// signal's exporter unbuilt and is the setup error, never a setup failure.
/// </summary>
[Collection("OpenTelemetry")]
public sealed class OtlpTlsTests : ListenerTestBase
{
    private string Missing => Path.Combine(Pki.Dir, "missing.pem");

    [Fact]
    public void Resolve_NothingConfiguredIsNeitherMaterialNorAProblem() =>
        Assert.Equal(new OtlpTlsResult(null, null), OtlpTls.Resolve("metrics", "", "", ""));

    [Theory]
    [InlineData("CERTIFICATE")]
    [InlineData("CLIENT_CERTIFICATE")]
    [InlineData("CLIENT_KEY")]
    public void Resolve_AnUnreadableFileNamesItsVariableAndPath(string kind)
    {
        string File(string k, string good) => k == kind ? Missing : good;
        var ca = File("CERTIFICATE", Pki.CaFile);
        var cert = File("CLIENT_CERTIFICATE", Pki.ClientCert);
        var key = File("CLIENT_KEY", Pki.ClientKey);

        var shared = OtlpTls.Resolve("metrics", ca, cert, key);
        Assert.Null(shared.Tls);
        Assert.StartsWith($"OTEL_EXPORTER_OTLP_{kind}={Missing}: ", shared.Problem);
        Assert.True(shared.Problem!.Length > $"OTEL_EXPORTER_OTLP_{kind}={Missing}: ".Length);

        SetEnv($"OTEL_EXPORTER_OTLP_TRACES_{kind}", Missing);
        Assert.StartsWith($"OTEL_EXPORTER_OTLP_TRACES_{kind}={Missing}: ", OtlpTls.Resolve("traces", ca, cert, key).Problem);
    }

    [Fact]
    public void Resolve_ADirectoryIsUnreadable() =>
        Assert.StartsWith($"OTEL_EXPORTER_OTLP_CERTIFICATE={Pki.Dir}: ", OtlpTls.Resolve("logs", Pki.Dir, "", "").Problem);

    [Theory]
    [InlineData("")]
    [InlineData("not a certificate\n")]
    [InlineData("-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n")]
    public void Resolve_ACaFileWithoutACertificate(string text)
    {
        var path = Pki.Write("bad-ca.crt", text);
        Assert.Equal(new OtlpTlsResult(null, $"OTEL_EXPORTER_OTLP_CERTIFICATE={path}: no PEM certificates"),
            OtlpTls.Resolve("metrics", path, "", ""));
    }

    [Fact]
    public void Resolve_ACaBundleWithAMalformedBlockAfterAGoodOne()
    {
        var path = Pki.Write("mixed-ca.crt",
            File.ReadAllText(Pki.CaFile) + "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n");
        Assert.Equal($"OTEL_EXPORTER_OTLP_CERTIFICATE={path}: no PEM certificates", OtlpTls.Resolve("metrics", path, "", "").Problem);
    }

    [Fact]
    public void Resolve_HalfAPairIsAProblem()
    {
        Assert.Equal(
            $"OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE={Pki.ClientCert}: OTEL_EXPORTER_OTLP_CLIENT_KEY is not set",
            OtlpTls.Resolve("metrics", "", Pki.ClientCert, "").Problem);
        Assert.Equal(
            $"OTEL_EXPORTER_OTLP_CLIENT_KEY={Pki.ClientKey}: OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE is not set",
            OtlpTls.Resolve("metrics", "", "", Pki.ClientKey).Problem);
    }

    [Fact]
    public void Resolve_ACertificateAndKeyThatDoNotPair()
    {
        var problem = OtlpTls.Resolve("metrics", "", Pki.ClientCert, Pki.KeyFile).Problem!;
        Assert.StartsWith(
            $"OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE={Pki.ClientCert}, OTEL_EXPORTER_OTLP_CLIENT_KEY={Pki.KeyFile}: ", problem);
        Assert.True(problem.Length > problem.LastIndexOf(": ", StringComparison.Ordinal) + 2);
    }

    [Fact]
    public void Resolve_AMalformedKey()
    {
        var key = Pki.Write("garbage.key", "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n");
        Assert.StartsWith(
            $"OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE={Pki.ClientCert}, OTEL_EXPORTER_OTLP_CLIENT_KEY={key}: ",
            OtlpTls.Resolve("metrics", "", Pki.ClientCert, key).Problem);
    }

    [Fact]
    public void Resolve_ReadsTheCaAndTheClientPair()
    {
        var tls = OtlpTls.Resolve("metrics", Pki.CaFile, Pki.ClientCert, Pki.ClientKey).Tls!;
        Assert.Single(tls.Roots!);
        Assert.True(tls.ClientCertificate!.HasPrivateKey);
        var caOnly = OtlpTls.Resolve("metrics", Pki.CaFile, "", "").Tls!;
        Assert.Null(caOnly.ClientCertificate);
        var pairOnly = OtlpTls.Resolve("metrics", "", Pki.ClientCert, Pki.ClientKey).Tls!;
        Assert.Null(pairOnly.Roots);
    }

    [Fact]
    public void Validate_ChainsToTheRootsAndKeepsOtherErrors()
    {
        using var server = X509Certificate2.CreateFromPemFile(Pki.CertFile, Pki.KeyFile);
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
        using (var client = OtlpTls.Resolve("metrics", Pki.CaFile, Pki.ClientCert, Pki.ClientKey).Tls!
                   .CreateClient(TimeSpan.FromSeconds(7)))
        {
            Assert.Equal(TimeSpan.FromSeconds(7), client.Timeout);
            using var response = await Answered(token => client.GetAsync(Url("https"), token));
            Assert.Equal(200, (int)response.StatusCode);
        }
        using (var noClientCert = OtlpTls.Resolve("metrics", Pki.CaFile, "", "").Tls!.CreateClient(TimeSpan.FromSeconds(5)))
        {
            await Assert.ThrowsAnyAsync<HttpRequestException>(() => Answered(token => noClientCert.GetAsync(Url("https"), token)));
        }
        using var stranger = new TestPki();
        using var wrongCa = OtlpTls.Resolve("metrics", stranger.CaFile, Pki.ClientCert, Pki.ClientKey).Tls!
            .CreateClient(TimeSpan.FromSeconds(5));
        await Assert.ThrowsAnyAsync<HttpRequestException>(() => Answered(token => wrongCa.GetAsync(Url("https"), token)));
    }

    [Fact]
    public void Apply_InstallsTheClientFactoryOnlyWithTls()
    {
        var options = new OtlpExporterOptions();
        Endpoints.Apply(options, "https://collector:4318", "metrics", new Dictionary<string, string>());
        var defaultFactory = options.HttpClientFactory;
        Endpoints.Apply(options, "https://collector:4318", "metrics", new Dictionary<string, string>(),
            OtlpTls.Resolve("metrics", Pki.CaFile, "", "").Tls);
        Assert.NotSame(defaultFactory, options.HttpClientFactory);
        options.TimeoutMilliseconds = 1234;
        using var client = options.HttpClientFactory();
        Assert.Equal(TimeSpan.FromMilliseconds(1234), client.Timeout);
    }

    // ── what setup does with a problem ───────────────────────────────────────

    private TelemetryConfig Configured(bool failOpen, params string[] badSignals)
    {
        var config = TelemetryConfig.Default();
        config.Tracing.Enabled = true;
        config.Logging.OtlpEnabled = true;
        config.Exporter.LogsFailOpen = failOpen;
        config.Exporter.TracesFailOpen = failOpen;
        config.Exporter.MetricsFailOpen = failOpen;
        config.Logging.OtlpEndpoint = "http://127.0.0.1:9";
        config.Tracing.OtlpEndpoint = "http://127.0.0.1:9";
        config.Metrics.OtlpEndpoint = "http://127.0.0.1:9";
        config.Metrics.Exporters = ["otlp", "prometheus"];
        foreach (var signal in badSignals)
        {
            if (signal == "logs") config.Logging.OtlpCertificate = Missing;
            if (signal == "traces") config.Tracing.OtlpCertificate = Missing;
            if (signal == "metrics") config.Metrics.OtlpCertificate = Missing;
        }
        return config;
    }

    [Theory]
    [InlineData("logs", true)]
    [InlineData("traces", true)]
    [InlineData("metrics", true)]
    [InlineData("logs", false)]
    [InlineData("traces", false)]
    [InlineData("metrics", false)]
    public void UnreadableTls_LeavesThatExporterUnbuiltWithoutFailingSetup(string signal, bool failOpen)
    {
        ProvideTelemetry.SetupTelemetry(Configured(failOpen, signal));
        var problem = $"OTEL_EXPORTER_OTLP_CERTIFICATE={Missing}: ";
        Assert.StartsWith(problem, ProvideTelemetry.GetHealthSnapshot().SetupError);
        Assert.DoesNotContain("; ", ProvideTelemetry.GetHealthSnapshot().SetupError);
        var warning = Assert.Single(Warnings);
        Assert.Equal("otlp.tls_file_unreadable", warning.Message);
        Assert.Equal(signal, warning.Fields["signal"]);
        Assert.Equal(ProvideTelemetry.GetHealthSnapshot().SetupError, warning.Fields["error"]);

        var providers = ProvideTelemetry.GetRuntimeStatus().Providers;
        Assert.Equal(signal != "logs", providers.Logs);
        Assert.Equal(signal != "traces", providers.Traces);
        // Metrics keep the pull reader even without the OTLP one.
        Assert.True(providers.Metrics);
        Assert.Equal(PrometheusEndpoint.Ready, PrometheusEndpoint.Status);
        ProvideTelemetry.Counter("still.served").Add(1);
        Assert.Contains("still_served_total 1\n", Scrape());
    }

    [Fact]
    public void UnreadableTls_WithoutTheReaderMetricsAreNotInstalled()
    {
        var config = Configured(true, "metrics");
        config.Metrics.Exporters = ["otlp"];
        ProvideTelemetry.SetupTelemetry(config);
        Assert.False(ProvideTelemetry.GetRuntimeStatus().Providers.Metrics);
        Assert.Equal(PrometheusEndpoint.NotSelected, PrometheusEndpoint.Status);
    }

    [Fact]
    public void UnreadableTls_SeveralProblemsAreJoined()
    {
        var config = Configured(true, "traces", "logs");
        config.Metrics.Prometheus.Listen = "true";
        config.Metrics.Prometheus.WebConfig = Missing;
        ProvideTelemetry.SetupTelemetry(config);
        var parts = ProvideTelemetry.GetHealthSnapshot().SetupError.Split("; ");
        Assert.Equal(3, parts.Length);
        Assert.StartsWith("OTEL_EXPORTER_OTLP_CERTIFICATE=", parts[0]);
        Assert.StartsWith("OTEL_EXPORTER_OTLP_CERTIFICATE=", parts[1]);
        Assert.StartsWith("prometheus listener: ", parts[2]);
        Assert.Equal(["traces", "logs"], Warnings.Where(w => w.Message == "otlp.tls_file_unreadable").Select(w => w.Fields["signal"]));
    }

    [Fact]
    public void Environment_APerSignalOverrideWinsOverABadSharedFile()
    {
        SetEnv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:9");
        SetEnv("OTEL_EXPORTER_OTLP_CERTIFICATE", Missing);
        SetEnv("OTEL_EXPORTER_OTLP_METRICS_CERTIFICATE", Pki.CaFile);
        SetEnv("PROVIDE_TRACE_ENABLED", "false");
        SetEnv("PROVIDE_LOG_OTLP_ENABLED", "false");
        ProvideTelemetry.SetupTelemetry();
        Assert.Equal("", ProvideTelemetry.GetHealthSnapshot().SetupError);
        Assert.True(ProvideTelemetry.GetRuntimeStatus().Providers.Metrics);
        Assert.Empty(Warnings);
    }

    [Fact]
    public void Configure_RejectsNull()
    {
        using var backend = new OpenTelemetryBackend(TelemetryConfig.Default());
        Assert.Throws<ArgumentNullException>(() => backend.Configure(null!));
    }
}
