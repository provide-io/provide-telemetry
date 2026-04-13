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

func main() {
	cfg := logger.DefaultLogConfig()
	cfg.Format = logger.LogFormatJSON
	cfg.ServiceName = os.Getenv("PROVIDE_TELEMETRY_SERVICE_NAME")
	cfg.Output = os.Stderr
	logger.Configure(cfg)
	logger.Logger.Info("log.output.parity", "logger_name", "probe")
}
