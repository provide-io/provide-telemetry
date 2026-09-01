// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"errors"
	"testing"
)

// _failingWriter refuses every write, the way a pipe whose reader has exited, a
// full disk, a closed file or a dropped network sink does.
type _failingWriter struct{ writes int }

func (w *_failingWriter) Write(p []byte) (int, error) {
	w.writes++
	return 0, errors.New("sink refused the write")
}

// A record the destination refused is counted as an export failure.
//
// log/slog discards the error a handler returns, so without this the loss is
// invisible: the health snapshot reports the record as emitted and nothing
// anywhere reports that it never landed. WithLogOutput makes an arbitrary
// destination ordinary, so a failing one is no longer exotic.
func TestHealth_CountsAWriteFailureAsAnExportFailure(t *testing.T) {
	sink := &_failingWriter{}
	setupWithSink(t, sink)
	_resetHealth()

	GetLogger(context.Background(), "sink.test").Info("record.that.fails")

	if sink.writes == 0 {
		t.Fatal("the writer was never called; the test is not wired")
	}
	snapshot := GetHealthSnapshot()
	if snapshot.LogsExportFailures != 1 {
		t.Errorf("LogsExportFailures = %d, want 1", snapshot.LogsExportFailures)
	}
}

// A record the destination accepted is not counted as a failure.
func TestHealth_CountsNoExportFailureWhenTheWriteSucceeds(t *testing.T) {
	var sink _countingWriter
	setupWithSink(t, &sink)
	_resetHealth()

	GetLogger(context.Background(), "sink.test").Info("record.that.lands")

	if snapshot := GetHealthSnapshot(); snapshot.LogsExportFailures != 0 {
		t.Errorf("LogsExportFailures = %d, want 0", snapshot.LogsExportFailures)
	}
}

// _countingWriter accepts every write.
type _countingWriter struct{ writes int }

func (w *_countingWriter) Write(p []byte) (int, error) {
	w.writes++
	return len(p), nil
}
