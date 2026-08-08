// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Runtime.CompilerServices;

using Provide.Telemetry.OpenTelemetry;

namespace Provide.Telemetry.Tests;

/// <summary>
/// Installs the OTLP backend once for the whole suite.
/// </summary>
/// <remarks>
/// Registration is an application decision, so the core package no longer makes
/// it. These tests exercise the behavior an application gets after it opts in,
/// which means opting in exactly once, before any test runs — a module
/// initializer rather than a fixture, because <c>Testing.ResetForTests</c> tears
/// down the generation and would otherwise race a per-class hook.
/// </remarks>
internal static class BackendRegistration
{
    [ModuleInitializer]
    internal static void Install() => OpenTelemetryBackendRegistration.Register();
}
