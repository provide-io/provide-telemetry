// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"context"
	"log/slog"
	"os"
	"strings"
	"testing"
	"time"
)

// ── Handler basics ───────────────────────────────────────────────────────────

func TestPrettyHandler_FormatLine_PlainWhenColorsOff(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false
	var buf bytes.Buffer
	h := newPrettyHandlerWithColors(&buf, cfg, false)
	r := slog.NewRecord(time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC), slog.LevelInfo, "hello world", 0)
	r.AddAttrs(slog.String("k", "v"))
	if err := h.Handle(context.Background(), r); err != nil {
		t.Fatalf("Handle returned error: %v", err)
	}
	out := buf.String()
	if strings.Contains(out, "\x1b[") {
		t.Errorf("unexpected ANSI escape when colors=false: %q", out)
	}
	for _, want := range []string{"2026-01-02T03:04:05.000Z", "[info     ]", "hello world", `k="v"`} {
		if !strings.Contains(out, want) {
			t.Errorf("missing %q in output: %q", want, out)
		}
	}
	if !strings.HasSuffix(out, "\n") {
		t.Errorf("expected trailing newline: %q", out)
	}
}

func TestPrettyHandler_FormatLine_ANSIWhenColorsOn(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false
	cfg.Logging.PrettyKeyColor = "dim"
	cfg.Logging.PrettyValueColor = "cyan"
	var buf bytes.Buffer
	h := newPrettyHandlerWithColors(&buf, cfg, true)
	r := slog.NewRecord(time.Now(), slog.LevelWarn, "msg", 0)
	r.AddAttrs(slog.String("k", "v"))
	if err := h.Handle(context.Background(), r); err != nil {
		t.Fatalf("Handle returned error: %v", err)
	}
	out := buf.String()
	if !strings.Contains(out, _ansiYellow) {
		t.Errorf("expected warn color (yellow) in output: %q", out)
	}
	if !strings.Contains(out, _ansiDim) {
		t.Errorf("expected dim key color in output: %q", out)
	}
	if !strings.Contains(out, _ansiCyan) {
		t.Errorf("expected cyan value color in output: %q", out)
	}
	if !strings.Contains(out, _ansiReset) {
		t.Errorf("expected reset sequence in output: %q", out)
	}
}

// Timestamp suppressed when config flag off.
func TestPrettyHandler_TimestampOmitted(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.IncludeTimestamp = false
	var buf bytes.Buffer
	h := newPrettyHandlerWithColors(&buf, cfg, false)
	r := slog.NewRecord(time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC), slog.LevelInfo, "msg", 0)
	_ = h.Handle(context.Background(), r)
	if strings.Contains(buf.String(), "2026-01-02") {
		t.Errorf("expected timestamp omitted: %q", buf.String())
	}
}

// Zero-time records skip timestamp even when flag on.
func TestPrettyHandler_ZeroTimeSkipsTimestamp(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.IncludeTimestamp = true
	var buf bytes.Buffer
	h := newPrettyHandlerWithColors(&buf, cfg, false)
	var zero time.Time
	r := slog.NewRecord(zero, slog.LevelInfo, "msg", 0)
	_ = h.Handle(context.Background(), r)
	if strings.Contains(buf.String(), "0001") {
		t.Errorf("expected zero time suppressed: %q", buf.String())
	}
}

// Enabled respects level.
func TestPrettyHandler_EnabledFiltersBelowTrace(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	h := newPrettyHandlerWithColors(os.Stderr, cfg, false)
	if !h.Enabled(context.Background(), slog.LevelInfo) {
		t.Error("expected info to be enabled")
	}
	if !h.Enabled(context.Background(), LevelTrace) {
		t.Error("expected trace to be enabled")
	}
	// Below LevelTrace is disabled.
	if h.Enabled(context.Background(), slog.Level(-100)) {
		t.Error("expected level below trace to be disabled")
	}
}

// Level color mapping covers every supported level.
func TestLevelColorMap_AllLevels(t *testing.T) {
	cases := map[string]string{
		"critical": _ansiBoldRed,
		"error":    _ansiRed,
		"warning":  _ansiYellow,
		"warn":     _ansiYellow,
		"info":     _ansiGreen,
		"debug":    _ansiBlue,
		"trace":    _ansiCyan,
		"unknown":  "",
	}
	for in, want := range cases {
		if got := _levelColorMap(in); got != want {
			t.Errorf("_levelColorMap(%q)=%q want %q", in, got, want)
		}
	}
}

// _resolveNamedColor covers every supported alias + unknown fallback.
func TestResolveNamedColor_Map(t *testing.T) {
	cases := map[string]string{
		"dim":     _ansiDim,
		"bold":    _ansiBold,
		"red":     _ansiRed,
		"green":   _ansiGreen,
		"yellow":  _ansiYellow,
		"blue":    _ansiBlue,
		"cyan":    _ansiCyan,
		"white":   _ansiWhite,
		"":        "",
		"none":    "",
		"magenta": "",
	}
	for in, want := range cases {
		if got := _resolveNamedColor(in); got != want {
			t.Errorf("_resolveNamedColor(%q)=%q want %q", in, got, want)
		}
	}
	// Whitespace + upper-case handling.
	if got := _resolveNamedColor(" RED "); got != _ansiRed {
		t.Errorf("expected trimmed+lowered RED to resolve to red, got %q", got)
	}
}

// _levelName covers each branch in the level-to-name switch.
func TestLevelName_Branches(t *testing.T) {
	cases := map[slog.Level]string{
		LevelTrace:       "trace",
		slog.LevelDebug:  "debug",
		slog.LevelInfo:   "info",
		slog.LevelWarn:   "warning",
		slog.LevelError:  "error",
		slog.Level(1000): "error",
	}
	for lvl, want := range cases {
		if got := _levelName(lvl); got != want {
			t.Errorf("_levelName(%d)=%q want %q", lvl, got, want)
		}
	}
}

// _formatValue: strings are quoted, numbers plain.
func TestFormatValue_StringQuoted(t *testing.T) {
	if got := _formatValue("hello"); got != `"hello"` {
		t.Errorf("string value want %q, got %q", `"hello"`, got)
	}
	if got := _formatValue(42); got != "42" {
		t.Errorf("int value want %q, got %q", "42", got)
	}
	if got := _formatValue(nil); got != "<nil>" {
		t.Errorf("nil value want %q, got %q", "<nil>", got)
	}
}

// TTY detection: a bytes.Buffer is not an *os.File → colors disabled.
func TestNewPrettyHandler_NonFileWriterDisablesColors(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	var buf bytes.Buffer
	h := newPrettyHandler(&buf, cfg)
	if h.colors {
		t.Error("expected colors disabled for non-*os.File writer")
	}
}

// TTY detection: piped os.Stderr is not a char device → colors disabled.
func TestNewPrettyHandler_PipedFileDisablesColors(t *testing.T) {
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = r.Close() }()
	defer func() { _ = w.Close() }()
	cfg := DefaultTelemetryConfig()
	h := newPrettyHandler(w, cfg)
	if h.colors {
		t.Error("expected colors disabled when writer is a pipe (non-TTY)")
	}
}

// Terminal detection helper handles nil safely.
func TestIsTerminalFile_NilReturnsFalse(t *testing.T) {
	if _isTerminalFile(nil) {
		t.Error("expected _isTerminalFile(nil) to be false")
	}
}

// Terminal detection helper reports false for pipes.
func TestIsTerminalFile_PipeFalse(t *testing.T) {
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = r.Close() }()
	defer func() { _ = w.Close() }()
	if _isTerminalFile(w) {
		t.Error("expected _isTerminalFile on pipe to be false")
	}
}

// Terminal detection returns false for a closed *os.File (Stat error path).
func TestIsTerminalFile_ClosedFileReturnsFalse(t *testing.T) {
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	_ = r.Close()
	_ = w.Close()
	if _isTerminalFile(w) {
		t.Error("expected closed file Stat to fail → colors disabled")
	}
}

// WithAttrs + WithGroup accumulate and render in sorted order.
func TestPrettyHandler_WithAttrsAndGroup(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	var buf bytes.Buffer
	base := newPrettyHandlerWithColors(&buf, cfg, false)
	h1 := base.WithAttrs([]slog.Attr{slog.String("persistent", "yes")})
	h2 := h1.WithGroup("grp")
	r := slog.NewRecord(time.Time{}, slog.LevelInfo, "msg", 0)
	r.AddAttrs(slog.String("inline", "foo"))
	if err := h2.Handle(context.Background(), r); err != nil {
		t.Fatal(err)
	}
	out := buf.String()
	if !strings.Contains(out, `persistent="yes"`) {
		t.Errorf("missing persistent attr in output: %q", out)
	}
	if !strings.Contains(out, `grp.inline="foo"`) {
		t.Errorf("expected grouped key prefix: %q", out)
	}
}

// WithGroup("") is a no-op on the group stack (slog convention).
func TestPrettyHandler_WithEmptyGroupNoOp(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	var buf bytes.Buffer
	base := newPrettyHandlerWithColors(&buf, cfg, false)
	h := base.WithGroup("").(*_prettyHandler)
	if len(h.groups) != 0 {
		t.Errorf("empty group name should not push onto group stack, got %v", h.groups)
	}
}

// Nested groups flatten to dotted keys.
func TestPrettyHandler_NestedGroupAttr(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	var buf bytes.Buffer
	h := newPrettyHandlerWithColors(&buf, cfg, false)
	r := slog.NewRecord(time.Time{}, slog.LevelInfo, "msg", 0)
	r.AddAttrs(slog.Group("outer", slog.String("inner", "x"), slog.Group("mid", slog.Int("n", 1))))
	if err := h.Handle(context.Background(), r); err != nil {
		t.Fatal(err)
	}
	out := buf.String()
	if !strings.Contains(out, `outer.inner="x"`) {
		t.Errorf("expected outer.inner in output: %q", out)
	}
	if !strings.Contains(out, "outer.mid.n=1") {
		t.Errorf("expected nested group dotted key: %q", out)
	}
}

// Empty slog.Attr entries are skipped in formatAttrs.
func TestPrettyHandler_EmptyAttrSkipped(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	var buf bytes.Buffer
	h := newPrettyHandlerWithColors(&buf, cfg, false)
	r := slog.NewRecord(time.Time{}, slog.LevelInfo, "msg", 0)
	r.AddAttrs(slog.Attr{})
	r.AddAttrs(slog.String("k", "v"))
	if err := h.Handle(context.Background(), r); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(buf.String(), `k="v"`) {
		t.Errorf("expected k=v in output: %q", buf.String())
	}
}

// PrettyFields filter restricts which keys render.
func TestPrettyHandler_FieldsFilter(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.PrettyFields = []string{"keep"}
	var buf bytes.Buffer
	h := newPrettyHandlerWithColors(&buf, cfg, false)
	r := slog.NewRecord(time.Time{}, slog.LevelInfo, "msg", 0)
	r.AddAttrs(slog.String("keep", "k"), slog.String("drop", "d"))
	if err := h.Handle(context.Background(), r); err != nil {
		t.Fatal(err)
	}
	out := buf.String()
	if !strings.Contains(out, `keep="k"`) {
		t.Errorf("expected keep in output: %q", out)
	}
	if strings.Contains(out, `drop="d"`) {
		t.Errorf("expected drop filtered out: %q", out)
	}
}

// ── Integration with _telemetryHandler / _baseLogHandler / GetLogger ─────────

// _baseLogHandler returns a _prettyHandler when format=pretty.
func TestBaseLogHandler_PrettyBranch(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Format = LogFormatPretty
	h := _baseLogHandler(cfg)
	if _, ok := h.(*_prettyHandler); !ok {
		t.Fatalf("expected *_prettyHandler, got %T", h)
	}
}

// _baseLogHandler still returns text handler for console format.
func TestBaseLogHandler_ConsoleBranchUnchanged(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Format = LogFormatConsole
	h := _baseLogHandler(cfg)
	if _, ok := h.(*_prettyHandler); ok {
		t.Fatalf("expected text handler for console format, got *_prettyHandler")
	}
}

// Pretty renderer composes with _telemetryHandler — full chain produces output
// with service.name, message, etc.
func TestPrettyHandler_IntegratesWithTelemetryHandler(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Format = LogFormatPretty
	cfg.Logging.Sanitize = false
	cfg.ServiceName = "svc-pretty"
	cfg.Environment = "test"
	cfg.Version = "9.9.9"

	var buf bytes.Buffer
	base := newPrettyHandlerWithColors(&buf, cfg, false)
	wrapped := _newTelemetryHandler(base, cfg, "mymod")
	l := slog.New(wrapped)
	l.Info("user.event.happened", slog.String("k", "v"))

	out := buf.String()
	for _, want := range []string{
		`service.name="svc-pretty"`,
		`service.env="test"`,
		`service.version="9.9.9"`,
		`logger_name="mymod"`,
		"user.event.happened",
		`k="v"`,
	} {
		if !strings.Contains(out, want) {
			t.Errorf("missing %q in pretty output: %q", want, out)
		}
	}
}

// End-to-end via _configureLogger → os.Stderr pipe: output is plain (no ANSI)
// because the pipe is not a TTY.
func TestConfigureLogger_PrettyFormatNonTTY(t *testing.T) {
	setupFullSampling(t)

	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	origStderr := os.Stderr
	os.Stderr = w
	defer func() { os.Stderr = origStderr }()

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Format = LogFormatPretty
	cfg.Logging.Sanitize = false
	cfg.ServiceName = "pretty-pipe"
	_configureLogger(cfg)
	t.Cleanup(func() { _configureLogger(DefaultTelemetryConfig()) })

	Logger.Info("pretty.event.name")
	_ = w.Close()

	var buf bytes.Buffer
	_, _ = buf.ReadFrom(r)
	out := buf.String()
	if strings.Contains(out, "\x1b[") {
		t.Errorf("expected no ANSI escape codes when stderr is a pipe: %q", out)
	}
	if !strings.Contains(out, "[info     ]") {
		t.Errorf("expected padded info level token: %q", out)
	}
	if !strings.Contains(out, "pretty.event.name") {
		t.Errorf("expected message in output: %q", out)
	}
	if !strings.Contains(out, `service.name="pretty-pipe"`) {
		t.Errorf("expected service.name field: %q", out)
	}
}
