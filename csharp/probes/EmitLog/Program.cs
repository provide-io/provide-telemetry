// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;

// Env configured by parity harness:
// PROVIDE_LOG_FORMAT=json, PROVIDE_TELEMETRY_SERVICE_NAME=probe, etc.
Testing.ResetForTests();
ProvideTelemetry.SetupTelemetry();
ProvideTelemetry.SetTraceContext(
    "0af7651916cd43dd8448eb211c80319c",
    "b7ad6b7169203331");
var probe = ProvideTelemetry.GetLogger("probe");
probe.Info("log.output.parity");

// Then one record per rung of the ladder, so the cross-language check can see
// the level vocabulary at every severity rather than only at INFO.
foreach (var severity in Enum.GetValues<LogSeverity>())
{
    probe.Log(severity, $"log.level.vocab.{Levels.Name(severity)}");
}
