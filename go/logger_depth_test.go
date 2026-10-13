// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"runtime"
	"strings"
	"testing"
)

// _depthAdapter stands in for a host's bridge from another logging API.
type _depthAdapter struct{ logger *slog.Logger }

func (a _depthAdapter) Info(msg string) {
	LogDepth(context.Background(), a.logger, slog.LevelInfo, 1, msg, "via", "adapter")
}

func (a _depthAdapter) Plain(msg string) {
	a.logger.Info(msg) // the adapter's own frame: what LogDepth exists to avoid
}

func _depthLogger(t *testing.T, buf *bytes.Buffer) *slog.Logger {
	t.Helper()
	setupFullSampling(t)
	cfg := DefaultTelemetryConfig()
	cfg.Logging.IncludeCaller = true
	return newTestLogger(buf, cfg, "")
}

func _depthRecord(t *testing.T, buf *bytes.Buffer) map[string]any {
	t.Helper()
	var record map[string]any
	if err := json.Unmarshal([]byte(strings.TrimSpace(buf.String())), &record); err != nil {
		t.Fatalf("not JSON: %v: %s", err, buf.String())
	}
	return record
}

func TestLogDepth_NamesTheAdaptersCaller(t *testing.T) {
	var buf bytes.Buffer
	adapter := _depthAdapter{logger: _depthLogger(t, &buf)}

	_, _, line, _ := runtime.Caller(0)
	adapter.Info("depth.bridged") // line + 1

	record := _depthRecord(t, &buf)
	if record["filename"] != "logger_depth_test.go" || record["lineno"] != float64(line+1) {
		t.Fatalf("callsite = %v:%v, want logger_depth_test.go:%d", record["filename"], record["lineno"], line+1)
	}
	if record["msg"] != "depth.bridged" || record["via"] != "adapter" {
		t.Fatalf("record lost its message or attributes: %v", record)
	}
}

func TestLogDepth_WithoutItTheAdapterNamesItself(t *testing.T) {
	var buf bytes.Buffer
	adapter := _depthAdapter{logger: _depthLogger(t, &buf)}
	_, _, line, _ := runtime.Caller(0)
	adapter.Plain("depth.plain")
	if lineno := _depthRecord(t, &buf)["lineno"]; lineno == float64(line+1) {
		t.Fatalf("a plain slog call inside the adapter already named its caller; LogDepth would be unnecessary")
	}
}

func TestLogDepth_ZeroNamesTheDirectCaller(t *testing.T) {
	var buf bytes.Buffer
	logger := _depthLogger(t, &buf)
	_, _, line, _ := runtime.Caller(0)
	LogDepth(context.Background(), logger, slog.LevelInfo, 0, "depth.zero") // line + 1
	if lineno := _depthRecord(t, &buf)["lineno"]; lineno != float64(line+1) {
		t.Fatalf("lineno = %v, want %d", lineno, line+1)
	}
}

func TestLogDepth_ANegativeDepthIsTheDirectCaller(t *testing.T) {
	var buf bytes.Buffer
	logger := _depthLogger(t, &buf)
	_, _, line, _ := runtime.Caller(0)
	LogDepth(context.Background(), logger, slog.LevelInfo, -3, "depth.negative") // line + 1
	if lineno := _depthRecord(t, &buf)["lineno"]; lineno != float64(line+1) {
		t.Fatalf("lineno = %v, want %d", lineno, line+1)
	}
}

func TestLogDepth_ADisabledLevelLogsNothing(t *testing.T) {
	var buf bytes.Buffer
	logger := slog.New(slog.NewJSONHandler(&buf, &slog.HandlerOptions{Level: slog.LevelWarn}))
	LogDepth(context.Background(), logger, slog.LevelInfo, 0, "depth.disabled")
	if buf.Len() != 0 {
		t.Fatalf("a disabled level wrote %q", buf.String())
	}
}

func TestLogDepth_NilLoggerAndContextUseTheDefaults(t *testing.T) {
	var buf bytes.Buffer
	saved := slog.Default()
	slog.SetDefault(slog.New(slog.NewJSONHandler(&buf, nil)))
	t.Cleanup(func() { slog.SetDefault(saved) })

	//nolint:staticcheck // SA1012: a nil context is the case under test
	LogDepth(nil, nil, slog.LevelInfo, 0, "depth.defaults")
	if !strings.Contains(buf.String(), "depth.defaults") {
		t.Fatalf("nothing reached the default logger: %q", buf.String())
	}
}
