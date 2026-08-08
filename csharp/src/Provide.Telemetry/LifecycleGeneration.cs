// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

namespace Provide.Telemetry;

/// <summary>
/// One immutable snapshot of everything a lifecycle start published.
/// </summary>
/// <remarks>
/// Setup used to keep the config, the three provider booleans and the
/// setup-done flag as five independent static fields, so a reader between two
/// writes could observe a config from one generation and provider flags from
/// another. Publishing them as a single record makes that impossible: a reader
/// takes one reference and every field it sees came from the same start.
/// <para>
/// <see cref="Number"/> increases on every successful start so a caller can tell
/// "still running" from "restarted since I looked".
/// </para>
/// </remarks>
internal sealed record LifecycleGeneration(
    long Number,
    TelemetryConfig Config,
    ITelemetryBackend? Backend,
    RuntimeState State)
{
    /// <summary>Signals with an owned provider in this generation.</summary>
    public ProviderFlags Providers => Backend?.Providers ?? ProviderFlags.None;
}
