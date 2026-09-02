// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"io"
	"os"
	"reflect"
	"sync"
	"sync/atomic"
)

// The installed log sink lives here rather than on TelemetryConfig, next to the
// provider handles SetupTelemetry already keeps out of the config.
//
// A writer is a handle, so it cannot be one of the config's fields without
// breaking two of that type's contracts: loadRuntimeGeneration hands callers a
// deep copy that cannot reach live runtime state, and TelemetryConfig is the
// cross-language wire shape Rust deserializes on the far side of a
// ReconfigureResult. A handle survives neither a deep copy nor a JSON round
// trip.
//
// Keeping it out of the config also means no reload path can lose it. Every
// entry point that rebuilds the handler chain — ReconfigureTelemetry,
// UpdateRuntimeConfig, ReloadRuntimeFromEnv — rebuilds from a config, and the
// sink is not in one, so there is nothing to carry forward and nothing to
// forget.
var _activeLogSink atomic.Pointer[_logSink] //nolint:gochecknoglobals

// _logSink serializes writes to a host-supplied writer. Each slog handler owns a
// private mutex and GetLogger builds a fresh handler per call, so without this
// every logger in the process would write to the one shared writer unsynchronized.
// os.Stderr needs no such wrapper: it is a single descriptor whose small writes
// the kernel already serializes.
type _logSink struct {
	mu     sync.Mutex
	w      io.Writer
	colors bool
}

// _newLogSink wraps w, deciding once whether the destination can render ANSI.
// The decision is made here because the pretty renderer sees only the wrapper.
func _newLogSink(w io.Writer) *_logSink {
	return &_logSink{w: w, colors: _isTerminalWriter(w)}
}

func (s *_logSink) Write(p []byte) (int, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.w.Write(p)
}

// Flush drains a buffered writer. Held under the same lock as Write so a flush
// cannot interleave with a record being written.
func (s *_logSink) Flush() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	f, ok := s.w.(interface{ Flush() error })
	if !ok {
		return nil
	}
	return f.Flush()
}

// _isTerminalWriter reports whether ANSI colour suits w.
//
// An *os.File is probed directly. Anything else must declare itself by
// implementing IsTerminal() bool: a wrapper knows what it wraps, and nothing
// else can find out without adopting its file descriptor — os.NewFile sets a
// finalizer that closes the descriptor, which for a wrapper around os.Stderr
// would close the host's stderr.
//
// The file probe asks whether the terminal renders ANSI, not merely whether one
// is there. Off Windows those are the same question; on Windows a console
// renders escapes only once virtual-terminal processing is enabled on it.
func _isTerminalWriter(w io.Writer) bool {
	switch t := w.(type) {
	case *os.File:
		return _terminalRendersANSI(t)
	case interface{ IsTerminal() bool }:
		return t.IsTerminal()
	default:
		return false
	}
}

// _logOutput is where rendered records go: the installed sink, or os.Stderr when
// the host installed none.
func _logOutput() io.Writer {
	if s := _activeLogSink.Load(); s != nil {
		return s
	}
	return os.Stderr
}

// _installLogSink publishes w as the process log destination.
func _installLogSink(w io.Writer) {
	_activeLogSink.Store(_newLogSink(w))
}

// _clearLogSink returns logging to os.Stderr.
func _clearLogSink() {
	_activeLogSink.Store(nil)
}

// _flushLogSink drains the installed sink, if any.
func _flushLogSink() error {
	if s := _activeLogSink.Load(); s != nil {
		return s.Flush()
	}
	return nil
}

// _writerIsNil reports whether w is nil or a nil pointer inside a non-nil
// interface. The second case passes an ordinary `w != nil` check and panics on
// the first record, from inside a library whose contract is to degrade rather
// than take the host down.
func _writerIsNil(w io.Writer) bool {
	if w == nil {
		return true
	}
	v := reflect.ValueOf(w)
	return v.Kind() == reflect.Pointer && v.IsNil()
}
