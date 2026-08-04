// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

namespace Provide.Telemetry;

/// <summary>Base telemetry exception.</summary>
public class TelemetryError : Exception
{
    public TelemetryError(string message) : base(message) { }
    public TelemetryError(string message, Exception inner) : base(message, inner) { }
}

/// <summary>Configuration validation or setup error.</summary>
public class ConfigurationError : TelemetryError
{
    public ConfigurationError(string message) : base(message) { }
    public ConfigurationError(string message, Exception inner) : base(message, inner) { }
}

/// <summary>Event schema validation error.</summary>
public class EventSchemaError : TelemetryError
{
    public EventSchemaError(string message) : base(message) { }
}

/// <summary>Raised when a provider-owned field is mutated after setup.</summary>
public class ProviderImmutableError : TelemetryError
{
    public ProviderImmutableError(string message) : base(message) { }
}
