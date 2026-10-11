// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Globalization;
using System.Net.Security;
using System.Security.Authentication;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;

using YamlDotNet.Core;
using YamlDotNet.Serialization;

namespace Provide.Telemetry.OpenTelemetry.Prometheus;

/// <summary>The web config cannot be used; the listener must not start.</summary>
internal sealed class WebConfigException(string message) : Exception(message);

/// <summary>
/// Serves the listener's certificate, re-reading it when the certificate or key
/// file's modification time changes.
/// </summary>
/// <remarks>
/// Checked on each new connection, so rotation needs no restart. The first
/// load happens in the constructor, so a bad pair keeps the listener from
/// starting (fail closed).
/// </remarks>
internal sealed class TlsReloader
{
    private readonly object _gate = new();
    private (DateTime Cert, DateTime Key) _stamp;
    private X509Certificate2 _certificate;

    public TlsReloader(string certFile, string keyFile, string? caFile, string clientAuth, SslProtocols protocols)
    {
        CertFile = certFile;
        KeyFile = keyFile;
        ClientAuth = clientAuth;
        Protocols = protocols;
        ClientRoots = caFile is null ? null : LoadRoots(caFile);
        _stamp = Stamps();
        _certificate = Load();
    }

    public string CertFile { get; }
    public string KeyFile { get; }
    public string ClientAuth { get; }
    public SslProtocols Protocols { get; }
    public X509Certificate2Collection? ClientRoots { get; }

    private (DateTime, DateTime) Stamps()
    {
        // A missing file reads as 1601-01-01, which differs from any real stamp,
        // so the reload that follows reports it.
        return (File.GetLastWriteTimeUtc(CertFile), File.GetLastWriteTimeUtc(KeyFile));
    }

    private X509Certificate2 Load()
    {
        // Round-tripped through PKCS#12: an ephemeral PEM key cannot sign a
        // TLS handshake on Windows.
        using var pem = X509Certificate2.CreateFromPemFile(CertFile, KeyFile);
        return X509CertificateLoader.LoadPkcs12(pem.Export(X509ContentType.Pkcs12), null);
    }

    private static X509Certificate2Collection LoadRoots(string path)
    {
        var roots = new X509Certificate2Collection();
        roots.ImportFromPemFile(path);
        if (roots.Count == 0) throw new CryptographicException($"{path} holds no certificate");
        return roots;
    }

    /// <summary>The current certificate, rebuilt first if either file changed.</summary>
    public X509Certificate2 Certificate()
    {
        lock (_gate)
        {
            var stamp = Stamps();
            if (stamp != _stamp)
            {
                _certificate = Load();
                _stamp = stamp;
            }
            return _certificate;
        }
    }

    /// <summary>The server options for one handshake.</summary>
    public SslServerAuthenticationOptions Options() => new()
    {
        ServerCertificateSelectionCallback = (_, _) => Certificate(),
        EnabledSslProtocols = Protocols,
        ClientCertificateRequired = ClientAuth != WebConfigLoader.NoClientCert,
        CertificateRevocationCheckMode = X509RevocationMode.NoCheck,
        RemoteCertificateValidationCallback = (_, certificate, _, _) => VerifyClient(certificate),
    };

    /// <summary>Whether a client certificate (or its absence) satisfies client_auth_type.</summary>
    internal bool VerifyClient(X509Certificate? certificate)
    {
        if (certificate is null) return ClientAuth != WebConfigLoader.RequireAndVerifyClientCert;
        if (ClientRoots is null) return true; // NoClientCert: a certificate offered anyway is not checked
        using var chain = new X509Chain();
        chain.ChainPolicy.TrustMode = X509ChainTrustMode.CustomRootTrust;
        chain.ChainPolicy.CustomTrustStore.AddRange(ClientRoots);
        chain.ChainPolicy.RevocationMode = X509RevocationMode.NoCheck;
        using var leaf = X509CertificateLoader.LoadCertificate(certificate.GetRawCertData());
        return chain.Build(leaf);
    }
}

/// <summary>The listener's TLS and basic-auth settings.</summary>
internal sealed class WebSecurity
{
    // Compared against when the user is unknown, so a wrong user name costs the
    // same as a wrong password. Any well-formed cost-10 hash will do.
    private const string DummyHash = "$2a$10$WuJ86tQzfCxkRPXM1G759Oi0am1AacPdbzSZS/UqQ3ePrV6MohbZq";
    private static readonly Encoding StrictUtf8 =
        Encoding.GetEncoding("utf-8", EncoderFallback.ExceptionFallback, DecoderFallback.ExceptionFallback);

    private readonly HashSet<string> _verified = new(StringComparer.Ordinal);
    private readonly object _gate = new();

    public WebSecurity(IReadOnlyDictionary<string, string>? users = null, TlsReloader? tls = null)
    {
        Users = users ?? new Dictionary<string, string>();
        Tls = tls;
    }

    public IReadOnlyDictionary<string, string> Users { get; }

    public TlsReloader? Tls { get; }

    /// <summary>Whether an Authorization header satisfies basic auth (always, with no users).</summary>
    public bool Authorized(string? header)
    {
        if (Users.Count == 0) return true;
        var parts = header?.Split(' ', 2) ?? [];
        if (parts.Length != 2 || !parts[0].Equals("basic", StringComparison.OrdinalIgnoreCase)) return false;
        string decoded;
        try
        {
            decoded = StrictUtf8.GetString(Convert.FromBase64String(parts[1]));
        }
        catch (Exception ex) when (ex is FormatException or DecoderFallbackException)
        {
            return false;
        }
        var pair = decoded.Split(':', 2);
        return pair.Length == 2 && Authenticate(pair[0], pair[1]);
    }

    /// <summary>
    /// Check a user and password with bcrypt, caching successes by a digest of the pair.
    /// </summary>
    public bool Authenticate(string user, string password)
    {
        var digest = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes($"{user}\0{password}")));
        lock (_gate)
        {
            if (_verified.Contains(digest)) return true;
        }
        // An unknown user is checked against a dummy hash, so a wrong user name
        // costs the same as a wrong password.
        var known = Users.TryGetValue(user, out var hashed);
        var matches = BCrypt.Net.BCrypt.Verify(password, known ? hashed : DummyHash);
        if (!(known && matches)) return false;
        lock (_gate)
        {
            _verified.Add(digest);
        }
        return true;
    }
}

/// <summary>
/// Reads a Prometheus web config file, restricted to the keys
/// <c>prometheus_metrics.listener_security</c> lists. Any problem is a
/// <see cref="WebConfigException"/>.
/// </summary>
internal static class WebConfigLoader
{
    public const string NoClientCert = "NoClientCert";
    public const string RequireAndVerifyClientCert = "RequireAndVerifyClientCert";
    public const string VerifyClientCertIfGiven = "VerifyClientCertIfGiven";

    // Any password will do: bcrypt rejects a malformed hash whatever it is given.
    private const string HashProbe = "";

    private static readonly HashSet<string> TopKeys = new(StringComparer.Ordinal) { "tls_server_config", "basic_auth_users" };

    private static readonly HashSet<string> TlsKeys = new(StringComparer.Ordinal)
    {
        "cert_file", "key_file", "client_ca_file", "client_auth_type", "min_version",
    };

    private static readonly Dictionary<string, SslProtocols> MinVersions = new(StringComparer.Ordinal)
    {
        ["TLS12"] = SslProtocols.Tls12 | SslProtocols.Tls13,
        ["TLS13"] = SslProtocols.Tls13,
    };

    // No pattern variables in || conditions and no throw inside a catch block
    // below: a mutant of either leaves a variable unassigned or a path without a
    // return, which fails to compile, and Stryker then drops every mutant of the
    // whole method unscored. The failure is captured and thrown afterwards.
    public static WebSecurity Load(string path)
    {
        var data = ReadYaml(path);
        if (data is null) return new WebSecurity();
        var top = data as Dictionary<object, object?> ?? throw Unsupported(path);
        if (!top.Keys.All(k => k is string key && TopKeys.Contains(key))) throw Unsupported(path);
        var baseDir = Path.GetDirectoryName(Path.GetFullPath(path))!;
        return new WebSecurity(
            Users(top.GetValueOrDefault("basic_auth_users"), path),
            top.TryGetValue("tls_server_config", out var tls) ? Tls(tls, baseDir) : null);
    }

    private static WebConfigException Unsupported(string path) =>
        new($"web config {path}: only [basic_auth_users, tls_server_config] are supported");

    private static object? ReadYaml(string path)
    {
        Exception? failure = null;
        object? data = null;
        try
        {
            data = new DeserializerBuilder().Build().Deserialize<object?>(File.ReadAllText(path));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or YamlException)
        {
            failure = ex;
        }
        return failure is null ? data : throw new WebConfigException($"web config {path}: {failure.Message}");
    }


    private static Dictionary<string, string> Users(object? raw, string path)
    {
        if (raw is null) return [];
        var map = raw as Dictionary<object, object?> ?? throw new WebConfigException(
            $"web config {path}: basic_auth_users must map user names to bcrypt hashes");
        var users = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var (user, hashed) in map)
        {
            var hash = hashed as string;
            if (!IsBcryptHash(hash))
            {
                throw new WebConfigException($"web config {path}: basic_auth_users[{user}] is not a bcrypt hash");
            }
            users[Convert.ToString(user, CultureInfo.InvariantCulture)!] = hash!;
        }
        return users;
    }

    /// <summary>Whether bcrypt can parse <paramref name="hash"/>; it throws for a malformed one whatever the password.</summary>
    private static bool IsBcryptHash(string? hash)
    {
        var valid = true;
        try
        {
            BCrypt.Net.BCrypt.Verify(HashProbe, hash);
        }
        catch (Exception ex) when (ex is BCrypt.Net.SaltParseException or ArgumentException)
        {
            valid = false;
        }
        return valid;
    }

    private static TlsReloader Tls(object? raw, string baseDir)
    {
        var map = raw as Dictionary<object, object?> ?? throw UnsupportedTls();
        if (!map.Keys.All(k => k is string key && TlsKeys.Contains(key))) throw UnsupportedTls();
        string Get(string key) => map.GetValueOrDefault(key) as string ?? "";
        var cert = Get("cert_file");
        var key = Get("key_file");
        if (cert.Length == 0 || key.Length == 0) throw new WebConfigException("tls_server_config needs cert_file and key_file");
        var minVersion = Get("min_version") is { Length: > 0 } v ? v : "TLS12";
        if (!MinVersions.TryGetValue(minVersion, out var protocols))
        {
            throw new WebConfigException($"tls_server_config.min_version '{minVersion}': want TLS12 or TLS13");
        }
        var ca = Get("client_ca_file");
        var auth = Get("client_auth_type") is { Length: > 0 } a ? a : ca.Length > 0 ? RequireAndVerifyClientCert : NoClientCert;
        if (auth is not (NoClientCert or RequireAndVerifyClientCert or VerifyClientCertIfGiven))
        {
            throw new WebConfigException($"tls_server_config.client_auth_type '{auth}' is not supported");
        }
        if (auth != NoClientCert && ca.Length == 0)
        {
            throw new WebConfigException($"tls_server_config.client_auth_type {auth} needs client_ca_file");
        }
        Exception? failure = null;
        TlsReloader? reloader = null;
        try
        {
            reloader = new TlsReloader(
                Path.Combine(baseDir, cert), Path.Combine(baseDir, key),
                ca.Length > 0 ? Path.Combine(baseDir, ca) : null, auth, protocols);
        }
        catch (Exception ex) when (ex is IOException or CryptographicException or UnauthorizedAccessException)
        {
            failure = ex;
        }
        return reloader ?? throw new WebConfigException($"tls_server_config: {failure!.Message}");
    }

    private static WebConfigException UnsupportedTls() =>
        new("tls_server_config: only [cert_file, client_auth_type, client_ca_file, key_file, min_version] are supported");
}
