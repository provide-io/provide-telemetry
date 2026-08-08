// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using OpenTelemetry.Resources;

// This assembly's namespace nests inside Provide.Telemetry, so the unqualified
// name binds to the core resource ladder. Both are aliased so which one is meant
// is never in doubt.
using CoreResource = Provide.Telemetry.ResourceBuilder;
using OtelResourceBuilder = OpenTelemetry.Resources.ResourceBuilder;

namespace Provide.Telemetry.OpenTelemetry;

/// <summary>Bridges the core resource ladder onto an OTel resource builder.</summary>
internal static class OtelResource
{
    /// <summary>
    /// Build the resource for one lifecycle generation.
    /// </summary>
    /// <remarks>
    /// The precedence decision — detected, then environment, then explicit — is
    /// made once in core so all five SDKs share it. This function only renders
    /// the result: it starts from <c>CreateDefault</c> for the SDK-detected
    /// attributes and then overwrites with the merged map, which already carries
    /// the winning value for every key.
    /// </remarks>
    public static OtelResourceBuilder Build(TelemetryConfig config)
    {
        var attributes = CoreResource.Build(config);
        return OtelResourceBuilder.CreateDefault()
            .AddService(serviceName: config.ServiceName, serviceVersion: config.Version)
            .AddAttributes(attributes.Select(kv => new KeyValuePair<string, object>(kv.Key, kv.Value)));
    }
}
