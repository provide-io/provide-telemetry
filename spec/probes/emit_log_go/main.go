// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// Emit one canonical JSON log line to stderr for cross-language parity checking.
//
// Env vars (set by run_behavioral_parity.py --check-output before invoking):
//
//	PROVIDE_LOG_FORMAT=json
//	PROVIDE_TELEMETRY_SERVICE_NAME=probe
//	PROVIDE_LOG_INCLUDE_TIMESTAMP=false
//	PROVIDE_LOG_LEVEL=INFO
package main

import (
	"os"

	"github.com/provide-io/provide-telemetry/go/logger"
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
	_ = os.Stderr.Sync()
}
