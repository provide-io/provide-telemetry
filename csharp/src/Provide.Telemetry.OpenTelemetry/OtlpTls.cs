// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Net.Http;
using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;


namespace Provide.Telemetry.OpenTelemetry;

/// <summary>The outcome of resolving one signal's TLS files: the material, or why there is none.</summary>
internal sealed record OtlpTlsResult(OtlpTls? Tls, string? Problem);

/// <summary>
/// The TLS material for one signal's OTLP exporter: a private CA bundle and/or
/// a client certificate for mutual TLS.
/// </summary>
/// <remarks>
/// <c>prometheus_metrics.push_security</c>: a configured file that cannot be
/// read or loaded — a CA file with no PEM certificate, or a client certificate
/// and key that do not pair — leaves that signal's OTLP exporter unbuilt and
/// is reported as <c>setup_error</c> naming the variable and path. It is never
/// ignored in favour of the system trust store, and it never fails setup. The
/// CA bundle replaces the system roots for that signal; host-name checks still
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
    /// The variable a file came from: the per-signal one when it is set in the
    /// environment, else the shared one.
    /// </summary>
    internal static string VariableName(string signal, string kind)
    {
        var own = $"OTEL_EXPORTER_OTLP_{signal.ToUpperInvariant()}_{kind}";
        return string.IsNullOrEmpty(Environment.GetEnvironmentVariable(own)) ? $"OTEL_EXPORTER_OTLP_{kind}" : own;
    }

    /// <summary>
    /// Load one signal's files. No files gives neither material nor a problem;
    /// a problem reads <c>VAR=path: reason</c>, or <c>CERT_VAR=cert, KEY_VAR=key: reason</c> for a pair.
    /// </summary>
    public static OtlpTlsResult Resolve(string signal, string caFile, string certFile, string keyFile)
    {
        if (caFile.Length == 0 && certFile.Length == 0 && keyFile.Length == 0) return new(null, null);
        var caVar = VariableName(signal, "CERTIFICATE");
        var certVar = VariableName(signal, "CLIENT_CERTIFICATE");
        var keyVar = VariableName(signal, "CLIENT_KEY");
        foreach (var (name, path) in new[] { (caVar, caFile), (certVar, certFile), (keyVar, keyFile) })
        {
            if (path.Length > 0 && Unreadable(path) is { } reason) return new(null, $"{name}={path}: {reason}");
        }
        X509Certificate2Collection? roots = null;
        if (caFile.Length > 0)
        {
            roots = LoadRoots(caFile);
            if (roots is null) return new(null, $"{caVar}={caFile}: no PEM certificates");
        }
        if (certFile.Length == 0 && keyFile.Length > 0) return new(null, $"{keyVar}={keyFile}: {certVar} is not set");
        if (certFile.Length > 0 && keyFile.Length == 0) return new(null, $"{certVar}={certFile}: {keyVar} is not set");
        X509Certificate2? client = null;
        if (certFile.Length > 0)
        {
            (client, var reason) = LoadClientCertificate(certFile, keyFile);
            if (client is null) return new(null, $"{certVar}={certFile}, {keyVar}={keyFile}: {reason}");
        }
        return new(new OtlpTls(roots, client), null);
    }

    private static string? Unreadable(string path)
    {
        try
        {
            File.ReadAllBytes(path);
            return null;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return ex.Message;
        }
    }

    /// <summary>The certificates in a PEM bundle, or null when it holds none.</summary>
    private static X509Certificate2Collection? LoadRoots(string path)
    {
        var roots = new X509Certificate2Collection();
        try
        {
            roots.ImportFromPemFile(path);
        }
        catch (CryptographicException)
        {
            // A malformed block anywhere means the file is not a usable bundle,
            // even when a certificate before it was imported.
            roots.Clear();
        }
        return roots.Count > 0 ? roots : null;
    }

    /// <summary>
    /// The PEM pair as a certificate with a persisted key: an ephemeral PEM key
    /// cannot sign a TLS handshake on Windows, so it is round-tripped through PKCS#12.
    /// </summary>
    private static (X509Certificate2? Certificate, string? Reason) LoadClientCertificate(string certFile, string keyFile)
    {
        try
        {
            using var pem = X509Certificate2.CreateFromPemFile(certFile, keyFile);
            return (X509CertificateLoader.LoadPkcs12(pem.Export(X509ContentType.Pkcs12), null), null);
        }
        catch (Exception ex) when (ex is CryptographicException or ArgumentException)
        {
            // A key for another certificate is an ArgumentException; a malformed one a CryptographicException.
            return (null, ex.Message);
        }
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
