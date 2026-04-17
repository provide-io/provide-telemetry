// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"testing"
)

func TestGetLogger_OmitsTimestampWhenDisabled(t *testing.T) {
	setupFullSampling(t)

	r, w, _ := os.Pipe()
	origStderr := os.Stderr
	os.Stderr = w
	defer func() { os.Stderr = origStderr }()

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Format = LogFormatJSON
	cfg.Logging.IncludeTimestamp = false
	cfg.Logging.Sanitize = false
	_configureLogger(cfg)
	t.Cleanup(func() { _configureLogger(DefaultTelemetryConfig()) })

	l := GetLogger(context.Background(), "json-no-time")
	l.Info("timestamp check")
	_ = w.Close()

	var buf bytes.Buffer
	_, _ = buf.ReadFrom(r)
	out := buf.String()

	var m map[string]any
	if err := json.Unmarshal([]byte(out), &m); err != nil {
		t.Fatalf("GetLogger with timestamp disabled produced non-JSON output: %v\noutput: %s", err, out)
	}
	if _, ok := m["time"]; ok {
		t.Fatalf("expected GetLogger output to omit time field when timestamps are disabled: %s", out)
	}
}
