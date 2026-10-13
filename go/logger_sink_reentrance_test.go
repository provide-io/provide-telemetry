// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"
)

// _withinDeadline runs fn and fails the test if it has not returned within a
// few seconds — the visible form of a deadlock, rather than a hung suite.
func _withinDeadline(t *testing.T, fn func()) {
	t.Helper()
	done := make(chan struct{})
	go func() {
		defer close(done)
		fn()
	}()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("deadlocked: the call did not return")
	}
}

// _callbackWriter runs onWrite / onFlush from inside Write / Flush, the way a
// writer that reports its own trouble through the SDK would.
type _callbackWriter struct {
	buf     bytes.Buffer
	onWrite func()
	onFlush func()
	flushes int
}

func (w *_callbackWriter) Write(p []byte) (int, error) {
	if w.onWrite != nil {
		w.onWrite()
	}
	return w.buf.Write(p)
}

func (w *_callbackWriter) Flush() error {
	w.flushes++
	if w.onFlush != nil {
		w.onFlush()
	}
	return nil
}

func TestLogSink_WriterFrameNamesResolve(t *testing.T) {
	if !strings.HasSuffix(_writeLockedFrame, ".(*_logSink).writeLocked") {
		t.Fatalf("write frame resolved to %q", _writeLockedFrame)
	}
	if !strings.HasSuffix(_flushLockedFrame, ".(*_logSink).flushLocked") {
		t.Fatalf("flush frame resolved to %q", _flushLockedFrame)
	}
}

func TestLogSink_ReentrantWriteIsRefusedNotDeadlocked(t *testing.T) {
	w := &_callbackWriter{}
	sink := _newLogSink(w)
	var nestedN int
	var nestedErr error
	w.onWrite = func() {
		w.onWrite = nil // one nested call is enough
		nestedN, nestedErr = sink.Write([]byte("nested"))
	}

	_withinDeadline(t, func() {
		n, err := sink.Write([]byte("outer"))
		if n != len("outer") || err != nil {
			t.Errorf("outer write = (%d, %v)", n, err)
		}
	})
	if nestedN != 0 || !errors.Is(nestedErr, errLogWriterReentered) {
		t.Fatalf("nested write = (%d, %v), want (0, errLogWriterReentered)", nestedN, nestedErr)
	}
	if got := w.buf.String(); got != "outer" {
		t.Fatalf("delivered %q, want only the outer write", got)
	}
	// The lock was released: the sink still takes ordinary writes.
	if _, err := sink.Write([]byte("+after")); err != nil || w.buf.String() != "outer+after" {
		t.Fatalf("write after re-entrance = %v, buffer %q", err, w.buf.String())
	}
}

func TestLogSink_ReentranceFromFlushAndIntoFlush(t *testing.T) {
	w := &_callbackWriter{}
	sink := _newLogSink(w)
	var fromFlush, intoFlush error
	w.onFlush = func() {
		w.onFlush = nil
		_, fromFlush = sink.Write([]byte("from-flush"))
	}
	w.onWrite = func() {
		w.onWrite = nil
		intoFlush = sink.Flush()
	}

	_withinDeadline(t, func() {
		if err := sink.Flush(); err != nil {
			t.Errorf("outer flush: %v", err)
		}
		if _, err := sink.Write([]byte("outer")); err != nil {
			t.Errorf("outer write: %v", err)
		}
	})
	if !errors.Is(fromFlush, errLogWriterReentered) || !errors.Is(intoFlush, errLogWriterReentered) {
		t.Fatalf("nested results: write-from-flush %v, flush-from-write %v", fromFlush, intoFlush)
	}
	if w.flushes != 1 || w.buf.String() != "outer" {
		t.Fatalf("flushes %d, buffer %q", w.flushes, w.buf.String())
	}
}

// _recurse calls fn depth frames down, so a stack check has to read past its
// first buffer to find, or rule out, a writer frame.
func _recurse(depth int, fn func()) {
	if depth == 0 {
		fn()
		return
	}
	_recurse(depth-1, fn)
}

func TestLogSink_ReentranceFoundBelowADeepWriter(t *testing.T) {
	w := &_callbackWriter{}
	sink := _newLogSink(w)
	var nestedErr error
	w.onWrite = func() {
		w.onWrite = nil
		_recurse(3*_hostWriterStackDepth, func() { _, nestedErr = sink.Write([]byte("nested")) })
	}
	_withinDeadline(t, func() { _, _ = sink.Write([]byte("outer")) })
	if !errors.Is(nestedErr, errLogWriterReentered) {
		t.Fatalf("nested write under a deep writer = %v, want errLogWriterReentered", nestedErr)
	}
}

func TestInsideHostWriter_FalseOnADeepStackWithNoWriter(t *testing.T) {
	var inside bool
	_recurse(3*_hostWriterStackDepth, func() { inside = _insideHostWriter() })
	if inside {
		t.Fatal("a stack with no writer frame was reported as inside one")
	}
}

// _slowWriter widens the window in which the lock is held, so concurrent
// writers find it taken and go through the stack check before waiting.
type _slowWriter struct {
	mu    sync.Mutex // asserts the sink serialized: TryLock must always win
	lines []string
	t     *testing.T
}

func (w *_slowWriter) Write(p []byte) (int, error) {
	if !w.mu.TryLock() {
		w.t.Error("two writes reached the host writer at once")
		return 0, errors.New("unserialized")
	}
	defer w.mu.Unlock()
	runtime.Gosched()
	w.lines = append(w.lines, string(p))
	return len(p), nil
}

func TestLogSink_ConcurrentWritersAllDelivered(t *testing.T) {
	const goroutines, each = 16, 200
	w := &_slowWriter{t: t}
	sink := _newLogSink(w)
	var refused sync.Map
	var wg sync.WaitGroup
	for g := range goroutines {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := range each {
				if _, err := sink.Write(fmt.Appendf(nil, "%d-%d", g, i)); err != nil {
					refused.Store(fmt.Sprintf("%d-%d", g, i), err)
				}
			}
		}()
	}
	_withinDeadline(t, wg.Wait)
	refused.Range(func(k, v any) bool {
		t.Errorf("write %v refused: %v", k, v)
		return true
	})
	if len(w.lines) != goroutines*each {
		t.Fatalf("delivered %d writes, want %d", len(w.lines), goroutines*each)
	}
}

// End to end, in every format: a writer that reports through slog.Default —
// which setup points at this SDK, and which shares one renderer with the
// package logger — neither deadlocks nor sees its nested record, and the
// nested record is counted as a log export failure.
func TestWithLogOutput_WriterThatLogsBackDoesNotDeadlock(t *testing.T) {
	for _, format := range []string{LogFormatJSON, LogFormatConsole, LogFormatPretty} {
		t.Run(format, func(t *testing.T) {
			resetSetupState(t)
			t.Cleanup(func() { resetSetupState(t) })
			w := &_callbackWriter{}
			w.onWrite = func() { slog.Error("writer.reports.trouble") }

			cfg := DefaultTelemetryConfig()
			cfg.Logging.Format = format
			if _, err := SetupTelemetry(WithConfig(cfg), WithLogOutput(w)); err != nil {
				t.Fatal(err)
			}
			before := GetHealthSnapshot()

			_withinDeadline(t, func() {
				slog.Info("outer.record")
				Logger().Info("second.record")
			})

			after := GetHealthSnapshot()
			if got := after.LogsExportFailures - before.LogsExportFailures; got != 2 {
				t.Fatalf("export failures counted %d, want 2 (one per nested record)", got)
			}
			if got := after.LogsEmitted - before.LogsEmitted; got != 4 {
				t.Fatalf("emitted counted %d, want 4", got)
			}
			out := w.buf.String()
			if !strings.Contains(out, "outer.record") || !strings.Contains(out, "second.record") ||
				strings.Contains(out, "writer.reports.trouble") {
				t.Fatalf("unexpected delivery: %q", out)
			}
			_withinDeadline(t, func() {
				if err := ShutdownTelemetry(context.Background()); err != nil {
					t.Errorf("shutdown: %v", err)
				}
			})
			if w.flushes != 1 {
				t.Fatalf("shutdown flushed %d times, want 1", w.flushes)
			}
		})
	}
}

// Many goroutines logging through the package logger to one host writer: every
// record arrives and none is counted as a failure.
func TestWithLogOutput_ConcurrentLoggersLoseNothing(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	w := &_slowWriter{t: t}
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Format = LogFormatJSON
	if _, err := SetupTelemetry(WithConfig(cfg), WithLogOutput(w)); err != nil {
		t.Fatal(err)
	}
	before := GetHealthSnapshot().LogsExportFailures

	const goroutines, each = 8, 50
	var wg sync.WaitGroup
	for range goroutines {
		wg.Add(1)
		go func() {
			defer wg.Done()
			logger := GetLogger(context.Background(), "concurrent")
			for range each {
				logger.Info("concurrent.record")
			}
		}()
	}
	_withinDeadline(t, wg.Wait)
	if got := GetHealthSnapshot().LogsExportFailures - before; got != 0 {
		t.Fatalf("export failures counted %d, want 0", got)
	}
	if len(w.lines) != goroutines*each {
		t.Fatalf("delivered %d records, want %d", len(w.lines), goroutines*each)
	}
}

// ── _sinkHandler ─────────────────────────────────────────────────────────────

type _failingRenderer struct{ slog.Handler }

func (_failingRenderer) Handle(context.Context, slog.Record) error {
	return errors.New("render failed")
}

func TestSinkHandler_RenderFailureSkipsTheWrite(t *testing.T) {
	var buf bytes.Buffer
	h := _newSinkHandler(_newLogSink(&buf), func(w io.Writer) slog.Handler {
		return _failingRenderer{slog.NewJSONHandler(w, nil)}
	})
	err := h.Handle(context.Background(), slog.NewRecord(time.Time{}, slog.LevelInfo, "m", 0))
	if err == nil || buf.Len() != 0 {
		t.Fatalf("render failure = %v, wrote %q", err, buf.String())
	}
}

func TestSinkHandler_EnabledFollowsTheRenderer(t *testing.T) {
	h := _newSinkHandler(_newLogSink(io.Discard), func(w io.Writer) slog.Handler {
		return slog.NewJSONHandler(w, &slog.HandlerOptions{Level: slog.LevelWarn})
	})
	if h.Enabled(context.Background(), slog.LevelInfo) || !h.Enabled(context.Background(), slog.LevelError) {
		t.Fatal("Enabled did not follow the renderer's level")
	}
}

func TestSinkHandler_WithAttrsAndGroupReachTheRenderer(t *testing.T) {
	var buf bytes.Buffer
	var h slog.Handler = _newSinkHandler(_newLogSink(&buf), func(w io.Writer) slog.Handler {
		return slog.NewJSONHandler(w, nil)
	})
	h = h.WithAttrs([]slog.Attr{slog.String("bound", "yes")}).WithGroup("grp")
	slog.New(h).Info("m", "k", "v")
	out := buf.String()
	if !strings.Contains(out, `"bound":"yes"`) || !strings.Contains(out, `"grp":{"k":"v"}`) {
		t.Fatalf("derived handler lost attrs or group: %q", out)
	}
}

func TestSinkHandler_OversizedRecordIsWritten(t *testing.T) {
	var buf bytes.Buffer
	h := _newSinkHandler(_newLogSink(&buf), func(w io.Writer) slog.Handler {
		return slog.NewJSONHandler(w, nil)
	})
	logger := slog.New(h)
	big := strings.Repeat("x", 2*_sinkBufferMaxRetain)
	logger.Info(big)
	logger.Info("small")
	out := buf.String()
	if !strings.Contains(out, big) || !strings.Contains(out, `"msg":"small"`) {
		t.Fatal("records around an oversized one were not written")
	}
	if strings.Count(out, "\n") != 2 {
		t.Fatalf("want 2 lines, got %q", out[len(out)-60:])
	}
}
