// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package logger

import "io"

// Log format constants.
const (
	LogFormatConsole = "console"
	LogFormatJSON    = "json"
	LogFormatPretty  = "pretty"
)

// Log level constants.
const (
	LogLevelTrace    = "TRACE"
	LogLevelDebug    = "DEBUG"
	LogLevelInfo     = "INFO"
	LogLevelWarn     = "WARN"
	LogLevelWarning  = "WARNING"
	LogLevelError    = "ERROR"
	LogLevelCritical = "CRITICAL"
)

// LogConfig holds all configuration needed by the logger sub-package.
// The main telemetry package builds one of these from its TelemetryConfig.
type LogConfig struct {
	// Service metadata added to every log record.
	ServiceName string
	Environment string
	Version     string

	// Logging behaviour.
	Level        string            // default "INFO"
	Format       string            // "console" | "json" | "pretty"
	Output       io.Writer         // log destination; nil → os.Stderr
	Sanitize     bool              // PII sanitisation enabled
	PIIMaxDepth  int               // 0 → use SanitizePayload default of 8
	ModuleLevels map[string]string // per-module level overrides

	// Schema enforcement.
	StrictSchema bool
	RequiredKeys []string
}

// DefaultLogConfig returns a LogConfig with sensible defaults.
func DefaultLogConfig() LogConfig {
	return LogConfig{
		Level:  LogLevelInfo,
		Format: LogFormatConsole,
	}
}
