// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;

namespace Provide.Telemetry.OpenTelemetry;

/// <summary>Where the backend's own warnings go: the SDK logger, or a test's capture.</summary>
internal static class SdkWarnings
{
    internal static Action<string, IReadOnlyDictionary<string, object?>> Warn { get; set; } = DefaultWarn;

    internal static void DefaultWarn(string message, IReadOnlyDictionary<string, object?> fields) =>
        Logging.GetLogger("provide.telemetry.otel").Warning(message, fields);
}
