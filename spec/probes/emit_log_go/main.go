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

const (
	traceID = "0af7651916cd43dd8448eb211c80319c"
	spanID  = "b7ad6b7169203331"
)

func main() {
	_, _ = telemetry.SetupTelemetry()
	ctx := telemetry.SetTraceContext(context.Background(), traceID, spanID)
	log := telemetry.GetLogger(ctx, "probe")
	log.Info("log.output.parity", "event", "log.output.parity")

	// Then one record per rung of the ladder, so the cross-language check can
	// see the level vocabulary at every severity rather than only at INFO.
	for _, name := range []string{"TRACE", "DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"} {
		event := "log.level.vocab." + name
		log.Log(context.Background(), telemetry.ParseLevel(name), event, "event", event)
	}
	_ = os.Stderr.Sync()
}
