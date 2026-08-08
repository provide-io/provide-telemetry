// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

namespace Provide.Telemetry;

/// <summary>
/// Resolves OTel resource identity across the three precedence layers.
/// </summary>
/// <remarks>
/// The ladder is detected &lt; environment &lt; explicit, pinned by the
/// <c>resource_precedence</c> fixture in <c>spec/behavioral_fixtures.yaml</c>.
/// "Explicit" means a config value that differs from the framework default: a
/// service that never set <c>PROVIDE_TELEMETRY_SERVICE_NAME</c> carries
/// <c>provide-service</c>, and treating that as a deliberate choice would let it
/// silently outrank an <c>OTEL_SERVICE_NAME</c> the operator did set.
/// </remarks>
public static class ResourceBuilder
{
    /// <summary>Resource key for the service name.</summary>
    public const string ServiceNameKey = "service.name";

    /// <summary>Resource key for the deployment environment.</summary>
    public const string EnvironmentKey = "deployment.environment";

    /// <summary>Resource key for the service version.</summary>
    public const string VersionKey = "service.version";

    private const string DefaultServiceName = "provide-service";
    private const string DefaultEnvironment = "dev";
    private const string DefaultVersion = "0.0.0";

    /// <summary>
    /// Merge detected, environment and explicit attributes into one resource map.
    /// </summary>
    /// <param name="config">Resolved runtime config.</param>
    /// <param name="detected">
    /// Attributes an SDK discovered about the host. Lowest precedence.
    /// </param>
    public static Dictionary<string, string> Build(
        TelemetryConfig config,
        IReadOnlyDictionary<string, string>? detected = null)
    {
        ArgumentNullException.ThrowIfNull(config);
        var resource = new Dictionary<string, string>(StringComparer.Ordinal);

        if (detected is not null)
        {
            foreach (var (key, value) in detected) resource[key] = value;
        }

        foreach (var (key, value) in FromEnvironment()) resource[key] = value;
        foreach (var (key, value) in Explicit(config)) resource[key] = value;

        return resource;
    }

    /// <summary>
    /// Identity attributes the caller genuinely chose, plus any extra ones.
    /// </summary>
    public static Dictionary<string, string> Explicit(TelemetryConfig config)
    {
        ArgumentNullException.ThrowIfNull(config);
        var explicitAttributes = new Dictionary<string, string>(StringComparer.Ordinal);
        Add(explicitAttributes, ServiceNameKey, config.ServiceName, DefaultServiceName);
        Add(explicitAttributes, EnvironmentKey, config.Environment, DefaultEnvironment);
        Add(explicitAttributes, VersionKey, config.Version, DefaultVersion);
        foreach (var (key, value) in config.ResourceAttributes) explicitAttributes[key] = value;
        return explicitAttributes;
    }

    /// <summary>
    /// Read <c>OTEL_SERVICE_NAME</c> and <c>OTEL_RESOURCE_ATTRIBUTES</c>.
    /// </summary>
    /// <remarks>
    /// <c>OTEL_SERVICE_NAME</c> is applied after the attribute list because the
    /// OTel specification gives the dedicated variable the higher precedence of
    /// the two.
    /// </remarks>
    private static Dictionary<string, string> FromEnvironment()
    {
        var fromEnvironment = new Dictionary<string, string>(StringComparer.Ordinal);
        var raw = System.Environment.GetEnvironmentVariable("OTEL_RESOURCE_ATTRIBUTES");
        if (!string.IsNullOrWhiteSpace(raw))
        {
            foreach (var pair in raw.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
            {
                var separator = pair.IndexOf('=');
                if (separator <= 0) continue;
                fromEnvironment[pair[..separator].Trim()] = pair[(separator + 1)..].Trim();
            }
        }

        var serviceName = System.Environment.GetEnvironmentVariable("OTEL_SERVICE_NAME");
        if (!string.IsNullOrWhiteSpace(serviceName)) fromEnvironment[ServiceNameKey] = serviceName;
        return fromEnvironment;
    }

    private static void Add(Dictionary<string, string> target, string key, string value, string frameworkDefault)
    {
        if (string.IsNullOrEmpty(value) || string.Equals(value, frameworkDefault, StringComparison.Ordinal)) return;
        target[key] = value;
    }
}
