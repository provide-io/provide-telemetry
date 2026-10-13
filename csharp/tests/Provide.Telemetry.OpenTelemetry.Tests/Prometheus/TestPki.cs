// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Net;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;

namespace Provide.Telemetry.OpenTelemetry.Tests.Prometheus;

/// <summary>A throwaway CA with a server and a client certificate, written as PEM files.</summary>
internal sealed class TestPki : IDisposable
{
    private readonly ECDsa _caKey = ECDsa.Create(ECCurve.NamedCurves.nistP256);
    private readonly X509Certificate2 _ca;

    public TestPki()
    {
        Dir = Directory.CreateTempSubdirectory("provide-pki-").FullName;
        var request = new CertificateRequest("CN=test CA", _caKey, HashAlgorithmName.SHA256);
        request.CertificateExtensions.Add(new X509BasicConstraintsExtension(true, false, 0, true));
        request.CertificateExtensions.Add(new X509KeyUsageExtension(
            X509KeyUsageFlags.KeyCertSign | X509KeyUsageFlags.CrlSign, true));
        request.CertificateExtensions.Add(new X509SubjectKeyIdentifierExtension(request.PublicKey, false));
        _ca = request.CreateSelfSigned(DateTimeOffset.UtcNow.AddHours(-1), DateTimeOffset.UtcNow.AddHours(1));
        CaFile = Write("ca.crt", _ca.ExportCertificatePem());
        (CertFile, KeyFile) = Issue("server", "1.3.6.1.5.5.7.3.1");
        (ClientCert, ClientKey) = Issue("client", "1.3.6.1.5.5.7.3.2");
    }

    public string Dir { get; }
    public string CaFile { get; }
    public string CertFile { get; }
    public string KeyFile { get; }
    public string ClientCert { get; }
    public string ClientKey { get; }

    public X509Certificate2Collection Roots()
    {
        var roots = new X509Certificate2Collection();
        roots.ImportFromPemFile(CaFile);
        return roots;
    }

    public string Write(string name, string text)
    {
        var path = Path.Combine(Dir, name);
        File.WriteAllText(path, text);
        return path;
    }

    /// <summary>Issue a leaf for localhost / 127.0.0.1 / ::1 and write its PEM pair under <paramref name="name"/>.</summary>
    public (string Cert, string Key) Issue(string name, string usage)
    {
        using var key = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        var request = new CertificateRequest($"CN={name}", key, HashAlgorithmName.SHA256);
        request.CertificateExtensions.Add(new X509BasicConstraintsExtension(false, false, 0, true));
        request.CertificateExtensions.Add(new X509EnhancedKeyUsageExtension([new Oid(usage)], false));
        var san = new SubjectAlternativeNameBuilder();
        san.AddDnsName("localhost");
        san.AddIpAddress(IPAddress.Loopback);
        san.AddIpAddress(IPAddress.IPv6Loopback);
        request.CertificateExtensions.Add(san.Build());
        request.CertificateExtensions.Add(X509AuthorityKeyIdentifierExtension.CreateFromCertificate(_ca, true, false));
        var serial = RandomNumberGenerator.GetBytes(8);
        serial[0] &= 0x7f;
        using var cert = request.Create(_ca.SubjectName, X509SignatureGenerator.CreateForECDsa(_caKey),
            DateTimeOffset.UtcNow.AddMinutes(-30), DateTimeOffset.UtcNow.AddMinutes(50), serial);
        return (Write($"{name}.crt", cert.ExportCertificatePem()), Write($"{name}.key", key.ExportPkcs8PrivateKeyPem()));
    }

    /// <summary>The client certificate with its key, ready for an HttpClientHandler.</summary>
    public X509Certificate2 ClientCertificate()
    {
        using var pem = X509Certificate2.CreateFromPemFile(ClientCert, ClientKey);
        return X509CertificateLoader.LoadPkcs12(pem.Export(X509ContentType.Pkcs12), null);
    }

    public void Dispose()
    {
        _ca.Dispose();
        _caKey.Dispose();
        try { Directory.Delete(Dir, recursive: true); }
        catch (IOException) { /* best effort */ }
    }
}
