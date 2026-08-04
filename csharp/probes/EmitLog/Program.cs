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
ProvideTelemetry.GetLogger("probe").Info("log.output.parity");
