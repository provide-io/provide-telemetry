// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"os"
	"strings"
	"sync"
	"testing"
)

// setupWithSink installs w as the log destination and returns a logger bound to
// it. Every test here drives the writer through the public API rather than
// calling _baseLogHandler, because the reload paths that lose a writer are only
// reachable that way.
func setupWithSink(t *testing.T, w io.Writer) *slog.Logger {
	t.Helper()
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	t.Setenv("PROVIDE_LOG_FORMAT", LogFormatJSON)

	if _, err := SetupTelemetry(WithLogOutput(w)); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	return GetLogger(context.Background(), "sink.test")
}

// Records reach the writer the host installed, through the ordinary
// SetupTelemetry → GetLogger path.
func TestWithLogOutput_RoutesRecordsToTheWriter(t *testing.T) {
	var buf bytes.Buffer
	setupWithSink(t, &buf).Info("routed-to-installed-writer")

	if !strings.Contains(buf.String(), "routed-to-installed-writer") {
		t.Errorf("installed writer received %q, want the log record", buf.String())
	}
}

// Every renderer honours the installed writer, not just the JSON one.
func TestWithLogOutput_HonouredByEveryRenderer(t *testing.T) {
	for _, format := range []string{LogFormatJSON, LogFormatPretty, LogFormatConsole} {
		t.Run(format, func(t *testing.T) {
			resetSetupState(t)
			t.Cleanup(func() { resetSetupState(t) })
			t.Setenv("PROVIDE_LOG_FORMAT", format)

			var buf bytes.Buffer
			if _, err := SetupTelemetry(WithLogOutput(&buf)); err != nil {
				t.Fatalf("setup failed: %v", err)
			}
			GetLogger(context.Background(), "sink.test").Info("renderer-honours-sink")

			if !strings.Contains(buf.String(), "renderer-honours-sink") {
				t.Errorf("installed writer received %q, want the log record", buf.String())
			}
		})
	}
}

// A nil writer is never installed, so records keep going to os.Stderr.
func TestSetup_DefaultsToStderrWithoutWithLogOutput(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	t.Setenv("PROVIDE_LOG_FORMAT", LogFormatJSON)

	out := captureStderr(t, func() {
		if _, err := SetupTelemetry(); err != nil {
			t.Fatalf("setup failed: %v", err)
		}
		GetLogger(context.Background(), "sink.test").Info("routed-to-stderr")
	})

	if !strings.Contains(out, "routed-to-stderr") {
		t.Errorf("stderr received %q, want the log record", out)
	}
}

// ── The three reload paths ────────────────────────────────────────────────────
//
// Each of these reaches _configureLogger and rebuilds the handler chain. None of
// them can name a writer, so each one must leave the installed sink alone.

func TestWithLogOutput_SurvivesReconfigureTelemetry(t *testing.T) {
	var buf bytes.Buffer
	logger := setupWithSink(t, &buf)

	t.Setenv("PROVIDE_LOG_LEVEL", LogLevelDebug)
	next, err := ReconfigureTelemetry(context.Background())
	if err != nil {
		t.Fatalf("reconfigure failed: %v", err)
	}
	// Without this the test cannot tell a preserved writer from a reconfigure
	// that applied nothing at all. The signal is a level rather than a sampling
	// rate: a rate below 1.0 drops the very records the assertions look for.
	if next.Logging.Level != LogLevelDebug {
		t.Fatalf("level is %q, want the reconfigure to have applied DEBUG", next.Logging.Level)
	}

	logger.Info("after-reconfigure")
	GetLogger(context.Background(), "sink.test").Info("after-reconfigure-fresh")

	assertBothReached(t, &buf, "after-reconfigure", "after-reconfigure-fresh")
}

func TestWithLogOutput_SurvivesUpdateRuntimeConfig(t *testing.T) {
	var buf bytes.Buffer
	logger := setupWithSink(t, &buf)

	logging := GetRuntimeConfig().Logging
	logging.Level = LogLevelDebug
	if err := UpdateRuntimeConfig(RuntimeOverrides{Logging: &logging}); err != nil {
		t.Fatalf("update failed: %v", err)
	}
	if GetRuntimeConfig().Logging.Level != LogLevelDebug {
		t.Fatalf("level is %q, want the override to have applied DEBUG", GetRuntimeConfig().Logging.Level)
	}

	logger.Info("after-update")
	GetLogger(context.Background(), "sink.test").Info("after-update-fresh")

	assertBothReached(t, &buf, "after-update", "after-update-fresh")
}

func TestWithLogOutput_SurvivesReloadRuntimeFromEnv(t *testing.T) {
	var buf bytes.Buffer
	logger := setupWithSink(t, &buf)

	t.Setenv("PROVIDE_LOG_LEVEL", LogLevelDebug)
	if err := ReloadRuntimeFromEnv(); err != nil {
		t.Fatalf("reload failed: %v", err)
	}
	if GetRuntimeConfig().Logging.Level != LogLevelDebug {
		t.Fatalf("level is %q, want the reload to have applied DEBUG", GetRuntimeConfig().Logging.Level)
	}

	logger.Info("after-reload")
	GetLogger(context.Background(), "sink.test").Info("after-reload-fresh")

	assertBothReached(t, &buf, "after-reload", "after-reload-fresh")
}

// assertBothReached fails when either message is missing, naming which one — a
// logger vended before the reload and one vended after exercise different code
// paths and can fail independently.
func assertBothReached(t *testing.T, buf *bytes.Buffer, before, after string) {
	t.Helper()
	out := buf.String()
	for _, want := range []string{before, after} {
		if !strings.Contains(out, want) {
			t.Errorf("installed writer never received %q; it holds %q", want, out)
		}
	}
}

// ── Writer hygiene ────────────────────────────────────────────────────────────

// A typed-nil writer passes an interface nil-check and would panic on the first
// record. Setup rejects it instead: silently falling back to os.Stderr is the
// behind-the-caller's-back failure this option exists to prevent.
func TestWithLogOutput_RejectsTypedNilWriter(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	var typedNil *bytes.Buffer
	_, err := SetupTelemetry(WithLogOutput(typedNil))

	var cfgErr *ConfigurationError
	if !errors.As(err, &cfgErr) {
		t.Fatalf("setup returned %v, want a *ConfigurationError", err)
	}
}

// A plain nil is the same mistake spelled more simply, and the zero value of
// the option field cannot tell it apart from the option never being passed.
func TestWithLogOutput_RejectsNilWriter(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	_, err := SetupTelemetry(WithLogOutput(nil))

	var cfgErr *ConfigurationError
	if !errors.As(err, &cfgErr) {
		t.Fatalf("setup returned %v, want a *ConfigurationError", err)
	}
}

// A writer that is not a pointer cannot be a typed nil, and must be accepted.
func TestWithLogOutput_AcceptsANonPointerWriter(t *testing.T) {
	var buf bytes.Buffer
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	t.Setenv("PROVIDE_LOG_FORMAT", LogFormatJSON)

	if _, err := SetupTelemetry(WithLogOutput(termWriter{w: &buf})); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	GetLogger(context.Background(), "sink.test").Info("value-writer")

	if !strings.Contains(buf.String(), "value-writer") {
		t.Errorf("installed writer received %q, want the log record", buf.String())
	}
}

// A writer with nothing to flush is not an error — most writers have no Flush.
func TestShutdownTelemetry_AcceptsAnUnflushableWriter(t *testing.T) {
	var buf bytes.Buffer
	setupWithSink(t, &buf).Info("unbuffered-record")

	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("shutdown failed: %v", err)
	}
	if !strings.Contains(buf.String(), "unbuffered-record") {
		t.Errorf("sink holds %q, want the record", buf.String())
	}
}

// Concurrent loggers share one sink, and each handler owns a private mutex, so
// the sink must serialize writes itself. Meaningful under -race, which every CI
// job uses.
func TestWithLogOutput_ConcurrentLoggersDoNotRace(t *testing.T) {
	var buf bytes.Buffer
	setupWithSink(t, &buf)

	var wg sync.WaitGroup
	for i := range 8 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			GetLogger(context.Background(), "sink.test").Info("concurrent", slog.Int("n", i))
		}()
	}
	wg.Wait()

	if got := strings.Count(buf.String(), "concurrent"); got != 8 {
		t.Errorf("sink holds %d records, want 8", got)
	}
}

// A buffered writer holds its tail until something flushes it. Shutdown is the
// last moment a host can expect its records to have landed.
func TestShutdownTelemetry_FlushesABufferedWriter(t *testing.T) {
	var sink bytes.Buffer
	logger := setupWithSink(t, bufio.NewWriter(&sink))

	logger.Info("buffered-record")
	if sink.Len() != 0 {
		t.Fatalf("sink already holds %d bytes; the writer is not buffering", sink.Len())
	}

	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("shutdown failed: %v", err)
	}
	if !strings.Contains(sink.String(), "buffered-record") {
		t.Errorf("sink holds %q after shutdown, want the buffered record", sink.String())
	}
}

// ── The config stays serializable ─────────────────────────────────────────────

// TelemetryConfig is the cross-language wire shape: Rust deserializes it on the
// far side of a ReconfigureResult. A writer on the struct makes that impossible
// and serializes a wrapper's exported fields — a credential among them — past
// RedactConfig.
func TestTelemetryConfig_RoundTripsThroughJSON(t *testing.T) {
	data, err := json.Marshal(DefaultTelemetryConfig())
	if err != nil {
		t.Fatalf("marshal failed: %v", err)
	}
	var back TelemetryConfig
	if err := json.Unmarshal(data, &back); err != nil {
		t.Fatalf("unmarshal failed: %v", err)
	}
	if strings.Contains(string(data), "Output") {
		t.Errorf("config serializes an Output key: %s", data)
	}
}

// ── Terminal detection ────────────────────────────────────────────────────────

// An *os.File is probed directly. Any other writer decides for itself by
// implementing IsTerminal, and one that stays silent gets no colors — escape
// codes in a file a host is parsing are worse than a plain line on a terminal.
func TestIsTerminalWriter(t *testing.T) {
	if _isTerminalWriter(&bytes.Buffer{}) {
		t.Error("a bytes.Buffer reports as a terminal")
	}

	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("os.Pipe: %v", err)
	}
	t.Cleanup(func() { _ = r.Close(); _ = w.Close() })

	if _isTerminalWriter(w) {
		t.Error("a pipe reports as a terminal")
	}
	if !_isTerminalWriter(termWriter{terminal: true}) {
		t.Error("a wrapper claiming a terminal is not believed")
	}
	if _isTerminalWriter(termWriter{terminal: false}) {
		t.Error("a wrapper disclaiming a terminal reports as one")
	}
}

// The pretty renderer colors a wrapped sink when the wrapper claims a terminal,
// which is the only way a host that prefixes its log stream keeps colors.
func TestWithLogOutput_PrettyColorsFollowTheWrapper(t *testing.T) {
	for _, terminal := range []bool{true, false} {
		t.Run(map[bool]string{true: "terminal", false: "not-terminal"}[terminal], func(t *testing.T) {
			var buf bytes.Buffer
			sink := _newLogSink(termWriter{terminal: terminal, w: &buf})
			h := newPrettyHandler(sink, DefaultTelemetryConfig())

			if h.colors != terminal {
				t.Errorf("pretty colors = %v, want %v", h.colors, terminal)
			}
		})
	}
}

// termWriter is a wrapper that declares its own terminal-ness, the way a host's
// prefixing writer must in order to keep pretty colors.
type termWriter struct {
	terminal bool
	w        io.Writer
}

func (x termWriter) Write(p []byte) (int, error) {
	if x.w == nil {
		return len(p), nil
	}
	return x.w.Write(p)
}
func (x termWriter) IsTerminal() bool { return x.terminal }
