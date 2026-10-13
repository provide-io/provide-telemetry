// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"context"
	"errors"
	"strings"
	"testing"
)

// _flakyWriter panics on its first write and flush, then behaves.
type _flakyWriter struct {
	buf          bytes.Buffer
	writePanics  int
	flushPanics  int
	flushedClean int
}

func (w *_flakyWriter) Write(p []byte) (int, error) {
	if w.writePanics > 0 {
		w.writePanics--
		panic("writer exploded")
	}
	return w.buf.Write(p)
}

func (w *_flakyWriter) Flush() error {
	if w.flushPanics > 0 {
		w.flushPanics--
		panic("flush exploded")
	}
	w.flushedClean++
	return nil
}

func TestLogSink_RecoversWriterPanicAndKeepsDelivering(t *testing.T) {
	w := &_flakyWriter{writePanics: 1}
	sink := _newLogSink(w)

	n, err := sink.Write([]byte("first"))
	if n != 0 || !errors.Is(err, errLogWriterPanicked) {
		t.Fatalf("panicking write = (%d, %v), want (0, errLogWriterPanicked)", n, err)
	}
	// The lock was released on the way out: a second write neither deadlocks
	// nor is lost.
	n, err = sink.Write([]byte("second"))
	if n != len("second") || err != nil {
		t.Fatalf("write after a panic = (%d, %v)", n, err)
	}
	if got := w.buf.String(); got != "second" {
		t.Fatalf("delivered %q, want only the second write", got)
	}
}

func TestLogSink_RecoversFlushPanic(t *testing.T) {
	w := &_flakyWriter{flushPanics: 1}
	sink := _newLogSink(w)

	if err := sink.Flush(); !errors.Is(err, errLogWriterPanicked) {
		t.Fatalf("panicking flush = %v, want errLogWriterPanicked", err)
	}
	if err := sink.Flush(); err != nil || w.flushedClean != 1 {
		t.Fatalf("flush after a panic = %v (clean flushes %d)", err, w.flushedClean)
	}
}

// End to end: the log call that hit the panic returns normally, the failure is
// counted where the handler counts any refused write, and the next record is
// delivered.
func TestWithLogOutput_PanickingWriterCostsOnlyItsRecord(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	w := &_flakyWriter{writePanics: 1, flushPanics: 1}

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Format = LogFormatJSON
	if _, err := SetupTelemetry(WithConfig(cfg), WithLogOutput(w)); err != nil {
		t.Fatal(err)
	}
	before := GetHealthSnapshot().LogsExportFailures

	Logger().Info("sink.panic.first")
	Logger().Info("sink.panic.second")

	if got := GetHealthSnapshot().LogsExportFailures - before; got != 1 {
		t.Fatalf("export failures counted %d, want 1", got)
	}
	out := w.buf.String()
	if strings.Contains(out, "sink.panic.first") || !strings.Contains(out, "sink.panic.second") {
		t.Fatalf("unexpected delivery: %q", out)
	}

	// A panicking Flush does not abort shutdown: the logger is still torn down.
	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("shutdown: %v", err)
	}
	if Logger() != nil || _activeLogSink.Load() != nil {
		t.Fatal("shutdown stopped at the panicking flush")
	}
}
