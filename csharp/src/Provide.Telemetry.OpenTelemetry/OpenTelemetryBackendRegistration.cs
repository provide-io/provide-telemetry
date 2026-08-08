// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;

namespace Provide.Telemetry.OpenTelemetry;

/// <summary>
/// Opt-in installation of the OpenTelemetry delivery backend.
/// </summary>
/// <remarks>
/// Call this once, before <c>SetupTelemetry</c>. It is the only edge between the
/// two packages: core never names this assembly, so an application that
/// references only <c>Provide.Telemetry</c> compiles, runs and logs — it simply
/// exports nothing.
/// </remarks>
public static class OpenTelemetryBackendRegistration
{
    /// <summary>Register the OTLP backend factory with the core runtime.</summary>
    public static void Register() =>
        TelemetryBackendRegistry.Register(config => new OpenTelemetryBackend(config));
}
