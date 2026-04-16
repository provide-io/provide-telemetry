// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// Emit one canonical JSON log line to stderr for cross-language parity checking.
package main

import (
	"context"
	"os"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

func main() {
	_, _ = telemetry.SetupTelemetry()
	log := telemetry.GetLogger(context.Background(), "probe")
	log.Info("log.output.parity", "event", "log.output.parity")
	_ = os.Stderr.Sync()
}
