// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"errors"
	"io"
	"os"
	"reflect"
	"runtime"
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
//
// The writer is the host's code, run inside a log call, so the sink puts two
// boundaries around it.
//
// A Write or Flush that panics becomes errLogWriterPanicked, which the
// telemetry handler counts as an export failure, and the lock is released on
// the way out so the next record is still delivered.
//
// A writer that logs through this SDK from inside Write or Flush re-enters the
// sink on the goroutine that holds its lock. Blocking there would deadlock, so
// that nested write is refused with errLogWriterReentered — counted, like a
// panic, as a log export failure — and the outer write carries on. Every other
// caller that finds the lock taken waits for it, as before: an ordinary
// concurrent writer is never dropped.
//
// Telling those two callers apart needs to know which goroutine holds the lock,
// and Go deliberately does not say. Recording a goroutine ID on every
// acquisition would mean parsing runtime.Stack on every record, which costs
// many times the write itself. The sink asks the question the other way round,
// and only once TryLock has failed: is the caller's own stack already inside
// one of the frames that call the host's writer? A re-entrant caller always
// is, because it was called from there; a concurrent one never is. The fast
// path — an uncontended lock — pays nothing for the check.
//
// The stack check cannot see which sink a writer frame belongs to. A writer
// that, during a reconfigure, logs from inside the old sink into a new sink
// some other goroutine holds is refused too. Waiting there is not safe either:
// that goroutine may itself be blocked on the writer the caller is inside.
type _logSink struct {
	mu     sync.Mutex
	w      io.Writer
	colors bool
}

// errLogWriterPanicked is what a write or flush reports when the host's writer
// panicked rather than returning.
var errLogWriterPanicked = errors.New("telemetry: log output writer panicked")

// errLogWriterReentered is what a write or flush reports when it was made from
// inside the host's writer, on the goroutine already holding the sink.
var errLogWriterReentered = errors.New("telemetry: record logged from inside the log output writer was dropped")

// _newLogSink wraps w, deciding once whether the destination can render ANSI.
// The decision is made here because the pretty renderer sees only the wrapper.
func _newLogSink(w io.Writer) *_logSink {
	return &_logSink{w: w, colors: _isTerminalWriter(w)}
}

func (s *_logSink) Write(p []byte) (int, error) {
	if !s.acquire() {
		return 0, errLogWriterReentered
	}
	defer s.mu.Unlock()
	return s.writeLocked(p)
}

// Flush drains a buffered writer. Held under the same lock as Write so a flush
// cannot interleave with a record being written. Shutdown calls it, so a
// panicking Flush is recovered here too rather than aborting the teardown.
func (s *_logSink) Flush() error {
	f, ok := s.w.(interface{ Flush() error })
	if !ok {
		return nil
	}
	if !s.acquire() {
		return errLogWriterReentered
	}
	defer s.mu.Unlock()
	return s.flushLocked(f)
}

// acquire takes the sink's lock and reports true, or reports false without
// taking it when the caller is already inside the host's writer.
func (s *_logSink) acquire() bool {
	if s.mu.TryLock() {
		return true
	}
	if _insideHostWriter() {
		return false
	}
	s.mu.Lock()
	return true
}

// writeLocked and flushLocked are the only frames that call into the host's
// writer; _insideHostWriter finds re-entrance by looking for them on the stack.
// They must stay real frames, so neither may be inlined.
//
//go:noinline
func (s *_logSink) writeLocked(p []byte) (n int, err error) {
	defer func() {
		if recover() != nil {
			n, err = 0, errLogWriterPanicked
		}
	}()
	return s.w.Write(p)
}

//go:noinline
func (s *_logSink) flushLocked(f interface{ Flush() error }) (err error) {
	defer func() {
		if recover() != nil {
			err = errLogWriterPanicked
		}
	}()
	return f.Flush()
}

// The fully qualified names of the two writer frames, resolved from the
// functions themselves so they follow the module path rather than repeat it.
var (
	_writeLockedFrame = _funcName((*_logSink).writeLocked) //nolint:gochecknoglobals
	_flushLockedFrame = _funcName((*_logSink).flushLocked) //nolint:gochecknoglobals
)

func _funcName(fn any) string {
	return runtime.FuncForPC(reflect.ValueOf(fn).Pointer()).Name()
}

// _hostWriterStackDepth is how many caller frames _insideHostWriter reads at
// first. A re-entrant call sits a few dozen frames above the writer frame; the
// buffer doubles until it holds the whole stack when that is not enough.
const _hostWriterStackDepth = 64

// _insideHostWriter reports whether the calling goroutine is running inside a
// sink's writeLocked or flushLocked. It walks the caller's own stack, so it is
// called only once the lock has been found taken.
func _insideHostWriter() bool {
	pcs := make([]uintptr, _hostWriterStackDepth)
	for {
		n := runtime.Callers(1, pcs)
		frames := runtime.CallersFrames(pcs[:n])
		for {
			frame, more := frames.Next()
			if frame.Function == _writeLockedFrame || frame.Function == _flushLockedFrame {
				return true
			}
			if !more {
				break
			}
		}
		if n < len(pcs) {
			return false
		}
		pcs = make([]uintptr, 2*len(pcs))
	}
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
