// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"io"
	"log/slog"
	"testing"
)

// The re-entrance guard sits on the path every record takes to a WithLogOutput
// writer. These measure that path uncontended, into io.Discard, so its cost is
// a number rather than a guess.

func BenchmarkLogSink_Write(b *testing.B) {
	sink := _newLogSink(io.Discard)
	line := []byte(`{"level":"INFO","message":"bench.log.emit","attempt":1}` + "\n")
	b.ReportAllocs()
	for b.Loop() {
		_, _ = sink.Write(line)
	}
}

// Contended, every writer that finds the lock taken walks its own stack once
// before waiting. This is the price of telling it apart from a re-entrant call.
func BenchmarkLogSink_WriteContended(b *testing.B) {
	sink := _newLogSink(io.Discard)
	line := []byte(`{"level":"INFO","message":"bench.log.emit","attempt":1}` + "\n")
	b.ReportAllocs()
	b.RunParallel(func(pb *testing.PB) {
		for pb.Next() {
			_, _ = sink.Write(line)
		}
	})
}

func BenchmarkLogEmit_ToLogOutput(b *testing.B) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Format = LogFormatJSON
	cfg.Logging.IncludeCaller = false
	_installLogSink(io.Discard)
	b.Cleanup(_clearLogSink)
	logger := slog.New(_newTelemetryHandler(_baseLogHandler(cfg), cfg, "bench"))
	b.ReportAllocs()
	for b.Loop() {
		logger.Info("bench.log.emit", "attempt", 1)
	}
}
