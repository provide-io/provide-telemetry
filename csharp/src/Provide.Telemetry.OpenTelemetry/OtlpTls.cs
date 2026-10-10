// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Net.Http;
using System.Net.Security;
using System.Security.Cryptography.X509Certificates;

using Provide.Telemetry;

namespace Provide.Telemetry.OpenTelemetry;

/// <summary>
/// The TLS material for one signal's OTLP exporter: a private CA bundle and/or
/// a client certificate for mutual TLS.
/// </summary>
/// <remarks>
/// <c>prometheus_metrics.push_security</c>: a configured file that cannot be
/// read fails the exporter's installation rather than being ignored in favour
/// of the system trust store. The CA bundle replaces the system roots for that
/// signal, as the OTel exporters in the other SDKs do; host-name checks still
/// apply.
/// </remarks>
internal sealed class OtlpTls
{
    private OtlpTls(X509Certificate2Collection? roots, X509Certificate2? clientCertificate)
    {
        Roots = roots;
        ClientCertificate = clientCertificate;
    }

    public X509Certificate2Collection? Roots { get; }

    public X509Certificate2? ClientCertificate { get; }

    /// <summary>
    /// Load the files for one signal, or return null when none is configured.
    /// </summary>
    /// <exception cref="ConfigurationError">A file cannot be read, or a certificate and key do not pair.</exception>
    public static OtlpTls? Load(string caFile, string certFile, string keyFile)
    {
        if (caFile.Length == 0 && certFile.Length == 0 && keyFile.Length == 0) return null;
        if ((certFile.Length == 0) != (keyFile.Length == 0))
        {
            throw new ConfigurationError("OTLP client certificate and client key must be set together");
        }
        try
        {
            return new OtlpTls(
                caFile.Length > 0 ? LoadRoots(caFile) : null,
                certFile.Length > 0 ? LoadClientCertificate(certFile, keyFile) : null);
        }
        catch (Exception ex) when (ex is not ConfigurationError)
        {
            throw new ConfigurationError($"OTLP TLS files: {ex.Message}", ex);
        }
    }

    private static X509Certificate2Collection LoadRoots(string path)
    {
        var roots = new X509Certificate2Collection();
        roots.ImportFromPemFile(path);
        if (roots.Count == 0) throw new ConfigurationError($"OTLP CA file {path} holds no certificate");
        return roots;
    }

    /// <summary>
    /// The PEM pair as a certificate with a persisted key: an ephemeral PEM key
    /// cannot sign a TLS handshake on Windows, so it is round-tripped through PKCS#12.
    /// </summary>
    private static X509Certificate2 LoadClientCertificate(string certFile, string keyFile)
    {
        using var pem = X509Certificate2.CreateFromPemFile(certFile, keyFile);
        return X509CertificateLoader.LoadPkcs12(pem.Export(X509ContentType.Pkcs12), null);
    }

    /// <summary>An HttpClient for the exporter, trusting <see cref="Roots"/> and presenting the client certificate.</summary>
    public HttpClient CreateClient(TimeSpan timeout)
    {
        var handler = new HttpClientHandler();
        if (ClientCertificate is not null) handler.ClientCertificates.Add(ClientCertificate);
        if (Roots is not null)
        {
            var roots = Roots;
            handler.ServerCertificateCustomValidationCallback = (_, certificate, _, errors) =>
                Validate(certificate, errors, roots);
        }
        return new HttpClient(handler) { Timeout = timeout };
    }

    /// <summary>
    /// Accept a server certificate that chains to <paramref name="roots"/> and
    /// names the host; the only error the system check may have reported is the
    /// chain it could not build without those roots.
    /// </summary>
    internal static bool Validate(X509Certificate2? certificate, SslPolicyErrors errors, X509Certificate2Collection roots)
    {
        if (certificate is null || (errors & ~SslPolicyErrors.RemoteCertificateChainErrors) != SslPolicyErrors.None)
        {
            return false;
        }
        using var chain = new X509Chain();
        chain.ChainPolicy.TrustMode = X509ChainTrustMode.CustomRootTrust;
        chain.ChainPolicy.CustomTrustStore.AddRange(roots);
        chain.ChainPolicy.RevocationMode = X509RevocationMode.NoCheck;
        return chain.Build(certificate);
    }
}
