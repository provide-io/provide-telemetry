// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"context"
	"log/slog"
	"strings"
	"testing"
)

// Every renderer honours Logging.Output, so a consumer that wraps the log
// stream — to prefix it, tee it, or discard it — gets the same treatment
// whichever format it selects.
func TestBaseLogHandler_WritesToConfiguredOutput(t *testing.T) {
	for _, format := range []string{LogFormatJSON, LogFormatPretty, LogFormatConsole} {
		t.Run(format, func(t *testing.T) {
			var buf bytes.Buffer
			cfg := DefaultTelemetryConfig()
			cfg.Logging.Format = format
			cfg.Logging.Output = &buf

			slog.New(_baseLogHandler(cfg)).Info("routed-to-configured-writer")

			if !strings.Contains(buf.String(), "routed-to-configured-writer") {
				t.Errorf("configured writer received %q, want the log record", buf.String())
			}
		})
	}
}

// A nil Output means the caller expressed no preference, so records land on
// os.Stderr.
func TestBaseLogHandler_DefaultsToStderrWhenOutputIsNil(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Format = LogFormatJSON
	cfg.Logging.Output = nil

	out := captureStderr(t, func() {
		slog.New(_baseLogHandler(cfg)).Info("routed-to-stderr")
	})

	if !strings.Contains(out, "routed-to-stderr") {
		t.Errorf("stderr received %q, want the log record", out)
	}
}

// Output is a cold field: it is installed once at setup and survives a
// reconfigure that reads fresh values from the environment. The environment
// cannot name a writer, so an env-sourced target always carries a nil Output —
// treating it as hot would silently return the process to os.Stderr.
func TestReconfigureTelemetry_PreservesLogOutput(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	var buf bytes.Buffer
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Output = &buf

	if _, err := SetupTelemetry(WithConfig(cfg)); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "0.5")
	next, err := ReconfigureTelemetry(context.Background())
	if err != nil {
		t.Fatalf("reconfigure failed: %v", err)
	}

	if next.Logging.Output != &buf {
		t.Errorf("Logging.Output is %v after reconfigure, want the writer installed at setup", next.Logging.Output)
	}
}
